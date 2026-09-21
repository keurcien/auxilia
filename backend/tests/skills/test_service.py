"""SkillService against a real (SQLite) database."""

from uuid import uuid4

import pytest

from app.exceptions import (
    AlreadyExistsError,
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

    created = await service.create(
        SkillSave(content=skill_markdown("deploy", "Ship it")), member
    )

    row = await agent_session.get(SkillDB, created.id)
    assert (row.name, row.description, row.revision) == ("deploy", "Ship it", 1)
    assert created.file_count == 0
    assert created.can_edit is True
    assert created.files == []


async def test_a_skill_written_here_is_refused_any_file(agent_session, member):
    """Files — references, assets and `scripts/` alike — reach the library
    only through a repository. Only the two in-app writes are guarded; the
    sync path builds its rows straight from `SkillCreateDB`."""
    service = SkillService(agent_session)
    files = [SkillFile(path="scripts/run.py", content="print(1)\n")]

    with pytest.raises(DomainValidationError, match=r"single SKILL\.md"):
        await service.create(
            SkillSave(content=skill_markdown("deploy", "Ship it"), files=files), member
        )

    created = await service.create(
        SkillSave(content=skill_markdown("deploy", "Ship it")), member
    )
    with pytest.raises(DomainValidationError, match=r"single SKILL\.md"):
        await service.update(
            created.id,
            SkillSave(
                content=skill_markdown("deploy", "Ship it"),
                files=[SkillFile(path="references/notes.md", content="x")],
                revision=created.revision,
            ),
            member,
        )


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
    # Two statements for the whole library, however many skills it holds: the
    # rows, then every skill->agent binding in one go for the avatar stacks.
    # What must never appear is a third that scales with the row count.
    assert len(statements) == 2
    [rows_query] = [q for q in statements.statements if "FROM skills" in q]
    assert "skills.content" not in rows_query
    assert "json_array_length(skills.files)" in rows_query


async def test_counts_scripts_and_agents_everywhere(agent_session, member):
    """The requirement chip and the USED column read the same two numbers
    from the list, the detail and the agent's own list: files under
    `scripts/` are scripts, everything else is not."""
    service = SkillService(agent_session)
    files = [
        SkillFile(path="scripts/clean.py", content=""),
        SkillFile(path="scripts/lib/util.py", content=""),
        SkillFile(path="references/guide.md", content=""),
        SkillFile(path="scripts.md", content=""),  # a file, not the folder
    ]
    skill = await seed_skill(agent_session, owner_id=member.id, files=files)
    await seed_skill(agent_session, owner_id=member.id, name="plain")
    first = await seed_agent(agent_session)
    second = await seed_agent(agent_session)
    await attach(agent_session, first.id, skill.id)
    await attach(agent_session, second.id, skill.id)

    by_name = {s.name: s for s in await service.list_summaries(member)}
    assert (by_name["report"].script_count, by_name["report"].agent_count) == (2, 2)
    assert (by_name["plain"].script_count, by_name["plain"].agent_count) == (0, 0)

    detail = await service.get(skill.id, member)
    assert (detail.script_count, detail.agent_count) == (2, 2)
    assert sorted(a.id for a in detail.agents) == sorted([first.id, second.id])
    assert detail.agents[0].name == "Agent"

    [attached] = await service.list_for_agent(first.id)
    assert attached.script_count == 2


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


async def test_the_library_is_one_namespace(agent_session, member):
    """A skill is addressed by its name, so the name is taken once, workspace
    wide. Refused here — at the door, where the caller can still do something
    about it — and not later at an agent's config save, where the remedy the
    message offers ("rename one of them") may not exist at all."""
    service = SkillService(agent_session)
    await service.create(SkillSave(content=skill_markdown("report")), member)

    with pytest.raises(AlreadyExistsError, match="already in the library"):
        await service.create(
            SkillSave(content=skill_markdown("report", "A different one")), member
        )
    # And a rename cannot walk onto a taken name either.
    other = await service.create(SkillSave(content=skill_markdown("digest")), member)
    with pytest.raises(AlreadyExistsError, match="already in the library"):
        await service.update(
            other.id, SkillSave(content=skill_markdown("report"), revision=1), member
        )


async def test_losing_the_name_race_is_a_409_not_a_500(agent_session, member):
    """Two requests naming the same skill at once both pass `_name_is_free` —
    neither can see the other's uncommitted row — and the unique index refuses
    the loser. That is the same answer as the lookup's, so it has to read the
    same way and not escape as an unhandled IntegrityError."""
    service = SkillService(agent_session)
    await service.create(SkillSave(content=skill_markdown("report")), member)

    # The lookup is what a concurrent writer would have missed; skipping it
    # leaves exactly the flush the loser of the race reaches.
    async def blind(_name: str) -> None:
        return None

    service._name_is_free = blind  # type: ignore[method-assign]
    with pytest.raises(AlreadyExistsError, match="already in the library"):
        await service.create(SkillSave(content=skill_markdown("report")), member)


async def test_enabling_a_skill_on_a_graph_needs_no_name_check(agent_session):
    """The union of a supervisor's and its subagents' skills cannot collide,
    because two different skills of one name do not exist. A binding is just a
    binding, and the same skill on both sides is one catalog entry."""
    service = SkillService(agent_session)
    supervisor = await seed_agent(agent_session)
    subagent = await seed_agent(agent_session)
    await link_subagent(agent_session, supervisor.id, subagent.id)
    report = await seed_skill(agent_session, owner_id=uuid4(), name="report")

    await service.set_for_agent(supervisor.id, [report.id])
    await service.set_for_agent(subagent.id, [report.id])
    assert [s.id for s in await service.list_for_agent(subagent.id)] == [report.id]
