"""Skill sources: sync, adopt, diff, detach — against SQLite, with the host
stubbed at the one seam that touches the network (`_resolve`)."""

from __future__ import annotations

import pytest

from app.exceptions import DomainValidationError, PermissionDeniedError
from app.skills.schemas import SkillSave, SkillSourceCreate, SkillSourceKind
from app.skills.service import SkillService
from app.skills.sources.service import SkillSourceService
from app.users.models import WorkspaceRole
from skillkit import (
    ArchiveSource,
    AuthenticationError,
    EmptyRepository,
    RevisionNotFound,
    SourceUnavailable,
)
from tests.skillkit.conftest import skill_md, tar_bytes
from tests.skills.conftest import attach, make_user, seed_agent, skill_markdown


pytestmark = pytest.mark.asyncio

URL = "https://github.com/acme/skills"


def tree_v1() -> dict[str, bytes]:
    return {
        "skills/weekly-brief/SKILL.md": skill_md(
            "weekly-brief",
            "Format the Monday sales recap. Use when asked for the weekly brief.",
        ),
        "skills/margin-audit/SKILL.md": skill_md(
            "margin-audit",
            "Recompute margins from raw exports. Use when margins look off.",
            body="Run `python scripts/clean.py`.\n",
        ),
        "skills/margin-audit/scripts/clean.py": b"print('v1')\n",
        "skills/broken/SKILL.md": b"---\nname: Broken Name\ndescription: x\n---\n\nbody\n",
    }


class StubHost:
    """`_resolve` replacement: serves whatever tree is current, or raises."""

    def __init__(self, tree: dict[str, bytes], revision: str = "aaa111"):
        self.tree, self.revision, self.error = tree, revision, None
        self.calls: list[tuple] = []

    async def __call__(self, kind, url, ref, subpath, token):
        self.calls.append((kind, url, ref, subpath, token))
        if self.error:
            raise self.error
        return ArchiveSource(
            tar_bytes(self.tree),
            url=url,
            ref=ref,
            revision=self.revision,
            kind=kind.value,
        ).resolve()


@pytest.fixture
def host(monkeypatch):
    stub = StubHost(tree_v1())
    monkeypatch.setattr(SkillSourceService, "_resolve", stub)
    return stub


@pytest.fixture
def admin():
    return make_user(WorkspaceRole.admin)


async def test_create_syncs_and_imports_valid_skills_only(agent_session, admin, host):
    service = SkillSourceService(agent_session)
    source = await service.create(
        SkillSourceCreate(url=URL + "/", token="ghp_x"), admin
    )

    assert source.kind == SkillSourceKind.github and source.name == "acme/skills"
    assert (
        source.has_token and host.calls[0][4] == "ghp_x"
    )  # decrypted for the host only
    assert (source.last_status, source.last_revision, source.skill_count) == (
        "ok",
        "aaa111",
        2,
    )
    [entry] = source.last_report
    assert entry.path == "skills/broken" and entry.issues[0].code == "E003"

    skills = SkillService(agent_session)
    by_name = {s.name: s for s in await skills.list_summaries(admin)}
    assert set(by_name) == {"weekly-brief", "margin-audit"}
    margin = by_name["margin-audit"]
    assert margin.source_id == source.id and margin.source_name == "acme/skills"
    assert (
        margin.source_path == "skills/margin-audit"
        and margin.source_revision == "aaa111"
    )
    assert margin.script_count == 1 and margin.digest.startswith("sha256:")
    assert not margin.update_available and not margin.can_edit and margin.can_manage
    with pytest.raises(DomainValidationError, match="synced from a repository"):
        await skills.update(
            margin.id,
            SkillSave(content=skill_markdown("margin-audit"), revision=1),
            admin,
        )


async def test_sync_makes_a_new_version_available_and_adopt_applies_it(
    agent_session, admin, host
):
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    margin = next(
        s for s in await skills.list_summaries(admin) if s.name == "margin-audit"
    )

    host.tree["skills/margin-audit/scripts/clean.py"] = b"print('v2')\n"
    host.tree["skills/margin-audit/SKILL.md"] = skill_md(
        "margin-audit",
        "Recompute margins from raw exports. Use before any pricing decision.",
        body="Run `python scripts/clean.py`.\n",
    )
    del host.tree["skills/weekly-brief/SKILL.md"]
    host.revision = "bbb222"
    synced = await sources.sync(source.id, admin)
    assert synced.last_revision == "bbb222" and synced.skill_count == 1

    by_name = {s.name: s for s in await skills.list_summaries(admin)}
    assert by_name["margin-audit"].update_available
    assert by_name["margin-audit"].source_revision == "aaa111"  # still pinned
    assert (
        by_name["weekly-brief"].missing_upstream
        and not by_name["weekly-brief"].update_available
    )

    detail = await skills.get(margin.id, admin)
    assert (
        detail.available.revision == "bbb222"
        and detail.files[0].content == "print('v1')\n"
    )

    diff = await skills.diff(margin.id, admin)
    assert diff.status == "changed" and diff.categories == ["description", "scripts"]
    assert (diff.old_revision, diff.new_revision) == ("aaa111", "bbb222")
    assert any(
        f.path == "scripts/clean.py" and "+print('v2')" in (f.unified or "")
        for f in diff.files
    )

    adopted = await skills.adopt(margin.id, admin)
    assert adopted.revision == 2 and adopted.source_revision == "bbb222"
    assert adopted.files[0].content == "print('v2')\n" and not adopted.update_available
    assert (await skills.diff(margin.id, admin)).status == "unchanged"
    # Adopting again is a no-op.
    assert (await skills.adopt(margin.id, admin)).revision == 2


async def test_adopt_refuses_a_rename_while_attached(agent_session, admin, host):
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    await sources.create(SkillSourceCreate(url=URL), admin)
    brief = next(
        s for s in await skills.list_summaries(admin) if s.name == "weekly-brief"
    )
    agent = await seed_agent(agent_session)
    await attach(agent_session, agent.id, brief.id)

    host.tree["skills/weekly-brief/SKILL.md"] = skill_md(
        "monday-brief",
        "Format the Monday sales recap. Use when asked for the weekly brief.",
    )
    # Not spec-valid (name ≠ directory), so it is reported, not imported…
    synced = await sources.sync((await sources.list(admin))[0].id, admin)
    assert synced.last_report[0].issues[0].code == "E003"
    # …and a valid rename in place still refuses to adopt while attached.
    del host.tree["skills/weekly-brief/SKILL.md"]
    host.tree["skills/monday-brief/SKILL.md"] = skill_md(
        "monday-brief",
        "Format the Monday sales recap. Use when asked for the weekly brief.",
    )
    await sources.sync((await sources.list(admin))[0].id, admin)
    by_name = {s.name: s for s in await skills.list_summaries(admin)}
    assert by_name["weekly-brief"].missing_upstream and "monday-brief" in by_name


async def test_failed_syncs_keep_state_and_tell_the_failures_apart(
    agent_session, admin, host
):
    sources = SkillSourceService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    assert source.skill_count == 2

    host.error = AuthenticationError("bad token")
    failed = await sources.sync(source.id, admin)
    # The resolver's own words, kept, plus the hint that a credential is what
    # the source is missing — the same hint preview raises.
    assert failed.last_status == "auth"
    assert failed.last_error.startswith("bad token")
    assert "add an access token" in failed.last_error
    assert failed.last_revision == "aaa111" and failed.skill_count == 2  # untouched

    host.error = SourceUnavailable("502")
    assert (await sources.sync(source.id, admin)).last_status == "unavailable"
    skills = SkillService(agent_session)
    assert len(await skills.list_summaries(admin)) == 2


async def test_delete_detaches_skills_into_in_app_skills(agent_session, admin, host):
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    await sources.delete(source.id, admin)

    assert await sources.list(admin) == []
    for summary in await skills.list_summaries(admin):
        assert (
            summary.source_id is None
            and summary.can_edit
            and not summary.update_available
        )


async def test_only_admins_manage_sources_and_hosts_need_a_kind(
    agent_session, admin, host
):
    sources = SkillSourceService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    member = make_user()
    with pytest.raises(PermissionDeniedError):
        await sources.sync(source.id, member)
    assert (await sources.list(member))[0].can_manage is False
    with pytest.raises(DomainValidationError, match="host type"):
        await sources.create(
            SkillSourceCreate(url="https://git.acme.io/team/skills"), admin
        )
    self_hosted = await sources.create(
        SkillSourceCreate(
            url="https://git.acme.io/team/skills", kind=SkillSourceKind.gitlab
        ),
        admin,
    )
    assert (
        self_hosted.kind == SkillSourceKind.gitlab
        and host.calls[-1][0] == SkillSourceKind.gitlab
    )
    with pytest.raises(DomainValidationError, match="already a source"):
        await sources.create(SkillSourceCreate(url=URL), admin)


async def test_preview_resolves_without_persisting(agent_session, admin, host):
    sources = SkillSourceService(agent_session)
    preview = await sources.preview(SkillSourceCreate(url=URL, ref="v1"))
    assert preview.revision == "aaa111" and preview.name == "acme/skills"
    assert {(s.name, s.ok) for s in preview.skills} == {
        ("weekly-brief", True),
        ("margin-audit", True),
        ("Broken Name", False),
    }
    assert await sources.list(admin) == []
    assert await SkillService(agent_session).list_summaries(admin) == []


async def test_preview_turns_a_private_repository_into_a_400_with_a_hint(
    agent_session, admin, host
):
    """A private repository answers 404, not 403 — the host will not admit it
    exists — so "not found" is what an admin sees after pasting a perfectly
    good URL. Preview used to let the `SkillkitError` escape as a 500, which
    read as "private repositories are unsupported"."""
    sources = SkillSourceService(agent_session)
    host.error = RevisionNotFound("acme/skills@main: repository, ref or path not found")

    with pytest.raises(DomainValidationError, match="add an access token"):
        await sources.preview(SkillSourceCreate(url=URL, ref="main"))

    # With a token supplied, the same failure means the token is the problem.
    with pytest.raises(DomainValidationError, match="still has read access"):
        await sources.preview(SkillSourceCreate(url=URL, ref="main", token="ghp_x"))

    host.error = AuthenticationError("github.com refused the request (401)")
    with pytest.raises(DomainValidationError, match="refused the request"):
        await sources.preview(SkillSourceCreate(url=URL, ref="main", token="ghp_x"))

    assert await sources.list(admin) == []


async def test_a_private_repository_syncs_when_the_token_reaches_the_resolver(
    agent_session, admin, host
):
    """The token is stored encrypted and handed back to the resolver on every
    sync — the whole of private-repository support."""
    sources = SkillSourceService(agent_session)

    source = await sources.create(
        SkillSourceCreate(url=URL, ref="main", token="ghp_secret"), admin
    )

    assert source.has_token is True
    assert source.last_status == "ok"
    assert host.calls[-1][4] == "ghp_secret"  # reached the resolver, decrypted
    row = await sources.repository.get(source.id)
    assert row.encrypted_token and "ghp_secret" not in row.encrypted_token

    host.calls.clear()
    await sources.sync(source.id, admin)
    assert host.calls[-1][4] == "ghp_secret"  # and again on every later sync


async def test_an_empty_repository_is_its_own_state_not_an_unreachable_host(
    agent_session, admin, host
):
    """GitHub answers 409 for a repository with no commits. Without its own
    type that landed in the `status >= 400` catch-all and surfaced as
    "github.com answered 409" under an UNREACHABLE badge — pointing at the
    network instead of at the empty repository."""
    sources = SkillSourceService(agent_session)
    host.error = EmptyRepository("acme/skills has no commits yet on github.com")

    with pytest.raises(DomainValidationError, match="no commits yet") as caught:
        await sources.preview(SkillSourceCreate(url=URL, ref="main"))
    # Not the credentials hint: the token is fine, the repository is bare.
    assert "access token" not in str(caught.value)
    assert "SKILL.md" in str(caught.value)

    host.error = None
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    host.error = EmptyRepository("acme/skills has no commits yet on github.com")
    failed = await sources.sync(source.id, admin)
    assert failed.last_status == "empty"
    assert "no commits yet" in failed.last_error


async def test_plan_says_what_a_sync_would_change_and_writes_nothing(
    agent_session, admin, host
):
    """The confirmation before a sync. `unchanged` and `updated` both leave
    the live skill alone — only `new` lands in the library on the spot — so
    the plan has to tell them apart, and it must not itself sync."""
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)

    tree = tree_v1()
    tree["skills/margin-audit/scripts/clean.py"] = b"print('v2')\n"  # changed
    tree["skills/kyc-check/SKILL.md"] = skill_md(
        "kyc-check", "Run the KYC checklist. Use when onboarding a brand."
    )  # new
    del tree["skills/weekly-brief/SKILL.md"]  # gone
    host.tree, host.revision = tree, "bbb222"

    plan = await sources.plan(source.id, admin)

    assert (plan.revision, plan.current_revision) == ("bbb222", "aaa111")
    assert {(e.name, e.status) for e in plan.entries} == {
        ("margin-audit", "updated"),
        ("kyc-check", "new"),
        ("weekly-brief", "gone"),
        ("Broken Name", "skipped"),
    }

    # Nothing was written: the source still sits on the old revision and the
    # library has not gained the new skill.
    unchanged = await sources.get(source.id, admin)
    assert unchanged.last_revision == "aaa111"
    assert "kyc-check" not in {s.name for s in await skills.list_summaries(admin)}

    # And syncing after it does exactly what the plan said.
    pinned = {s.name: s.digest for s in await skills.list_summaries(admin)}
    await sources.sync(source.id, admin)
    by_name = {s.name: s for s in await skills.list_summaries(admin)}
    assert "kyc-check" in by_name  # the `new` one landed
    assert by_name["weekly-brief"].missing_upstream  # the `gone` one was flagged
    # The `updated` one is untouched: a sync makes a version available, it does
    # not apply it. (Whether `update_available` resolves is a separate matter —
    # `latest_version` breaks ties on a random UUID, so it is not assertable.)
    assert by_name["margin-audit"].digest == pinned["margin-audit"]


async def test_a_source_is_its_url_ref_and_path(agent_session, admin, host):
    """Identity findings from review: `create` checked it, `update` did not,
    and nothing in the database held the line when two admins raced."""
    from app.skills.schemas import SkillSourcePatch

    sources = SkillSourceService(agent_session)
    first = await sources.create(SkillSourceCreate(url=URL, ref="main"), admin)
    other = await sources.create(SkillSourceCreate(url=URL, ref="next"), admin)

    # create: unchanged behaviour
    with pytest.raises(DomainValidationError, match="already a source"):
        await sources.create(SkillSourceCreate(url=URL, ref="main"), admin)

    # update: moving `other` onto `first`'s ref is the same collision
    with pytest.raises(DomainValidationError, match="already tracks"):
        await sources.update(other.id, SkillSourcePatch(ref="main"), admin)

    # and a no-op edit of a source onto its own identity is still fine
    await sources.update(first.id, SkillSourcePatch(ref="main"), admin)
