"""SkillService against a real (SQLite) database."""

from uuid import uuid4

import pytest

from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    StaleRevisionError,
)
from app.skills.models import SkillDB
from app.skills.schemas import SkillFile, SkillSave
from app.skills.service import SkillService
from tests.skills.conftest import (
    attach,
    link_subagent,
    make_user,
    seed_agent,
    seed_skill,
    skill_markdown,
)


pytestmark = pytest.mark.asyncio


async def test_create_derives_columns_from_the_document(agent_session, member):
    service = SkillService(agent_session)
    files = [SkillFile(path="scripts/run.py", content="print(1)\n")]

    created = await service.create(
        SkillSave(content=skill_markdown("deploy", "Ship it"), files=files), member
    )

    row = await agent_session.get(SkillDB, created.id)
    assert (row.name, row.description, row.revision) == ("deploy", "Ship it", 1)
    assert created.file_count == 1
    assert created.can_edit is True
    assert created.files == files


async def test_list_never_loads_files_and_counts_them(
    agent_session, member, statements
):
    service = SkillService(agent_session)
    await seed_skill(
        agent_session,
        owner_id=uuid4(),
        files=[SkillFile(path="a.py", content=""), SkillFile(path="b.py", content="")],
    )
    statements.reset()

    [summary] = await service.list_summaries(member)

    assert summary.file_count == 2
    assert summary.can_edit is False  # someone else's, and not an admin
    assert len(statements) == 1
    assert "skills.content" not in statements.statements[0]
    assert "json_array_length(skills.files)" in statements.statements[0]


async def test_every_user_reads_only_owner_or_admin_edits(agent_session, member, admin):
    owner = make_user()
    row = await seed_skill(agent_session, owner_id=owner.id)
    service = SkillService(agent_session)
    save = SkillSave(content=skill_markdown("report", "v2"), revision=1)

    assert (await service.get(row.id, member)).can_edit is False
    with pytest.raises(PermissionDeniedError):
        await service.update(row.id, save, member)
    with pytest.raises(PermissionDeniedError):
        await service.delete(row.id, member)

    assert (await service.update(row.id, save, admin)).description == "v2"
    assert (
        await service.update(
            row.id, SkillSave(content=skill_markdown("report", "v3"), revision=2), owner
        )
    ).revision == 3


async def test_update_refuses_a_stale_revision(agent_session, member):
    row = await seed_skill(agent_session, owner_id=member.id)
    service = SkillService(agent_session)

    await service.update(
        row.id, SkillSave(content=skill_markdown(), revision=1), member
    )
    with pytest.raises(StaleRevisionError):
        await service.update(
            row.id, SkillSave(content=skill_markdown(), revision=1), member
        )
    with pytest.raises(StaleRevisionError):
        await service.update(row.id, SkillSave(content=skill_markdown()), member)


async def test_rename_and_delete_are_refused_while_enabled_on_an_agent(
    agent_session, member
):
    row = await seed_skill(agent_session, owner_id=member.id)
    agent = await seed_agent(agent_session)
    await attach(agent_session, agent.id, row.id)
    service = SkillService(agent_session)

    with pytest.raises(DomainValidationError, match="renaming"):
        await service.update(
            row.id, SkillSave(content=skill_markdown("other"), revision=1), member
        )
    with pytest.raises(DomainValidationError, match="deleting"):
        await service.delete(row.id, member)

    # Same name, new body: allowed while attached — that is how skills update.
    updated = await service.update(
        row.id,
        SkillSave(content=skill_markdown("report", "Better"), revision=1),
        member,
    )
    assert updated.description == "Better"


async def test_delete_removes_an_unattached_skill(agent_session, member):
    row = await seed_skill(agent_session, owner_id=member.id)
    service = SkillService(agent_session)

    await service.delete(row.id, member)

    with pytest.raises(NotFoundError):
        await service.get(row.id, member)


async def test_export_names_the_archive_after_the_skill(agent_session):
    row = await seed_skill(agent_session, owner_id=uuid4(), name="export-me")
    name, archive = await SkillService(agent_session).export(row.id)
    assert name == "export-me"
    assert archive[:2] == b"PK"


async def test_set_for_agent_replaces_the_whole_set(agent_session):
    service = SkillService(agent_session)
    agent = await seed_agent(agent_session)
    a = await seed_skill(agent_session, owner_id=uuid4(), name="a")
    b = await seed_skill(agent_session, owner_id=uuid4(), name="b")
    c = await seed_skill(agent_session, owner_id=uuid4(), name="c")

    await service.set_for_agent(agent.id, [a.id, b.id])
    assert [s.name for s in await service.list_for_agent(agent.id)] == ["a", "b"]

    await service.set_for_agent(agent.id, [b.id, c.id, c.id])
    assert [s.name for s in await service.list_for_agent(agent.id)] == ["b", "c"]

    await service.set_for_agent(agent.id, [])
    assert await service.list_for_agent(agent.id) == []


async def test_set_for_agent_rejects_unknown_skills(agent_session):
    agent = await seed_agent(agent_session)
    with pytest.raises(NotFoundError):
        await SkillService(agent_session).set_for_agent(agent.id, [uuid4()])


async def test_one_skill_set_per_graph_refuses_two_skills_of_one_name(agent_session):
    """A supervisor and its subagents run with the union of their skills, so
    two *different* skills named alike cannot be enabled across the graph —
    whichever side is being edited. The same skill on both sides is fine."""
    service = SkillService(agent_session)
    supervisor = await seed_agent(agent_session)
    subagent = await seed_agent(agent_session)
    await link_subagent(agent_session, supervisor.id, subagent.id)
    report = await seed_skill(agent_session, owner_id=uuid4(), name="report")
    other_report = await seed_skill(agent_session, owner_id=uuid4(), name="report")
    await attach(agent_session, supervisor.id, report.id)

    with pytest.raises(
        DomainValidationError, match="Two different skills named 'report'"
    ):
        await service.set_for_agent(subagent.id, [other_report.id])
    with pytest.raises(
        DomainValidationError, match="Two different skills named 'report'"
    ):
        await service.set_for_agent(supervisor.id, [report.id, other_report.id])

    await service.set_for_agent(subagent.id, [report.id])  # same skill: one entry
    assert [s.id for s in await service.list_for_agent(subagent.id)] == [report.id]


async def test_ensure_unique_names_guards_a_subagent_joining(agent_session):
    """The check `SubagentService` runs before linking: the union of both
    sets must have unique names."""
    service = SkillService(agent_session)
    supervisor = await seed_agent(agent_session)
    joiner = await seed_agent(agent_session)
    await attach(
        agent_session,
        supervisor.id,
        (await seed_skill(agent_session, owner_id=uuid4(), name="x")).id,
    )
    await attach(
        agent_session,
        joiner.id,
        (await seed_skill(agent_session, owner_id=uuid4(), name="x")).id,
    )

    with pytest.raises(DomainValidationError):
        await service.ensure_unique_names([supervisor.id, joiner.id])
    # Each side alone is fine.
    await service.ensure_unique_names([supervisor.id])
    await service.ensure_unique_names([joiner.id])
