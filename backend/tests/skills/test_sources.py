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
        # `subpath` is passed through, as the real resolver does: it decides
        # which part of the tree is walked, and a stub that swallowed it made
        # every subpath test silently exercise the whole repository.
        return ArchiveSource(
            tar_bytes(self.tree),
            url=url,
            ref=ref,
            revision=self.revision,
            kind=kind.value,
            subpath=subpath,
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
    # The report is the whole sync, not only its failures: it is the only
    # record of what the sync did once the confirmation dialog is gone.
    assert {e.name: e.status for e in source.last_report} == {
        "weekly-brief": "new",
        "margin-audit": "new",
        "Broken Name": "skipped",
    }
    [entry] = [e for e in source.last_report if e.status == "skipped"]
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


async def test_delete_leaves_its_skills_detached_and_frozen(agent_session, admin, host):
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    await sources.delete(source.id, admin)

    assert await sources.list(admin) == []
    by_name = {s.name: s for s in await skills.list_summaries(admin)}
    assert set(by_name) == {"weekly-brief", "margin-audit"}
    margin = by_name["margin-audit"]
    # Detached: the pin and everything the repository gave it stay, so the
    # skill keeps running — the link, and only the link, is gone.
    assert margin.source_id is None and margin.source_name is None
    assert margin.digest is not None and margin.source_revision == "aaa111"
    assert margin.script_count == 1 and margin.file_count == 1
    detail = await skills.get(margin.id, admin)
    assert detail.files[0].content == "print('v1')\n"

    # Its content is frozen until the repository is connected again: the app
    # never writes files it did not author. Removing the row is not editing,
    # so that stays available, under the same in-use guard as any skill.
    assert not margin.can_edit and margin.can_manage
    assert not margin.update_available and not margin.missing_upstream
    with pytest.raises(DomainValidationError, match="no longer connected"):
        await skills.update(
            margin.id,
            SkillSave(content=skill_markdown("margin-audit"), revision=1),
            admin,
        )

    brief = by_name["weekly-brief"]
    agent = await seed_agent(agent_session)
    await attach(agent_session, agent.id, brief.id)
    with pytest.raises(DomainValidationError, match="Disable this skill"):
        await skills.delete(brief.id, admin)
    await skills.delete(margin.id, admin)
    assert [s.name for s in await skills.list_summaries(admin)] == ["weekly-brief"]


async def test_connecting_the_repository_again_re_pins_the_detached_skills(
    agent_session, admin, host
):
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    before = {s.name: s.id for s in await skills.list_summaries(admin)}
    agent = await seed_agent(agent_session)
    await attach(agent_session, agent.id, before["weekly-brief"])
    await sources.delete(source.id, admin)

    # The repository moved on while it was disconnected.
    host.tree["skills/margin-audit/scripts/clean.py"] = b"print('v2')\n"
    host.revision = "bbb222"
    reconnected = await sources.create(SkillSourceCreate(url=URL), admin)

    by_name = {s.name: s for s in await skills.list_summaries(admin)}
    # The same rows, claimed by name: no second copy of anything, and the
    # agent's binding never pointed at a row that went away.
    assert set(by_name) == {"weekly-brief", "margin-audit"}
    assert {name: s.id for name, s in by_name.items()} == before
    assert {s.source_id for s in by_name.values()} == {reconnected.id}
    assert by_name["weekly-brief"].can_manage and not by_name["weekly-brief"].can_edit
    # And the sync it missed is waiting, as an update rather than a rewrite.
    assert by_name["margin-audit"].update_available
    assert by_name["margin-audit"].source_revision == "aaa111"
    assert (await skills.adopt(by_name["margin-audit"].id, admin)).source_revision == (
        "bbb222"
    )


async def test_a_sync_never_claims_a_skill_written_in_the_app(
    agent_session, admin, host
):
    """The pin is `source_revision`, not `digest`: every save computes a
    digest, so an in-app skill must not read as detached and be swallowed by
    a repository that happens to use its name. The name is simply taken, and
    the repository's skill of that name is skipped and reported."""
    skills = SkillService(agent_session)
    mine = await skills.create(SkillSave(content=skill_markdown("margin-audit")), admin)
    assert mine.digest is not None and mine.can_edit

    sources = SkillSourceService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)

    still_mine = await skills.get(mine.id, admin)
    assert still_mine.source_id is None and still_mine.source_revision is None
    assert still_mine.can_edit and still_mine.can_manage
    # Not imported beside it under the same name: reported, for a human.
    assert {e.name: e.status for e in source.last_report}["margin-audit"] == "skipped"
    [entry] = [e for e in source.last_report if e.name == "margin-audit"]
    assert entry.issues[0].code == "W004"
    assert source.skill_count == 1
    assert [s.name for s in await skills.list_summaries(admin)].count(
        "margin-audit"
    ) == 1


async def test_one_spelling_per_repository(agent_session, admin, host):
    """A url is an identity twice over — a source *is* its (url, ref, path),
    and a detached skill is reclaimed by the repository whose url it carries.
    `…/skills.git` and `…/skills/` have to be the same repository, or
    reconnecting with a slightly different spelling silently imports nothing
    and reports every skill as a name already taken."""
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL + "/"), admin)
    assert source.url == URL
    before = {s.name: s.id for s in await skills.list_summaries(admin)}
    await sources.delete(source.id, admin)

    again = await sources.create(SkillSourceCreate(url=URL + ".git"), admin)
    assert again.url == URL
    assert {s.name: s.id for s in await skills.list_summaries(admin)} == before
    assert again.skill_count == 2


async def test_one_subpath_cannot_reclaim_another_subpaths_skill(
    agent_session, admin, host
):
    """A reclaim matches on where the skill sits in the repository, not on its
    name. Two sources can share a URL with different subpaths — `discover`
    strips the subpath, so both see a skill called `margin-audit` at the same
    relative path — and the URL alone cannot tell them apart. Matching on the
    name would hand one subpath's row, id and agent bindings to the other.
    """
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    host.tree = {
        "team-a/skills/margin-audit/SKILL.md": skill_md(
            "margin-audit", "Team A's audit. Use when margins look off."
        ),
        "team-b/skills/margin-audit/SKILL.md": skill_md(
            "margin-audit", "Team B's audit, a different procedure entirely."
        ),
    }
    team_a = await sources.create(SkillSourceCreate(url=URL, subpath="team-a"), admin)
    [skill] = await skills.list_summaries(admin)
    # Repo-root-relative, so the subpath is part of the identity.
    assert skill.source_path == "team-a/skills/margin-audit"
    await sources.delete(team_a.id, admin)

    team_b = await sources.create(SkillSourceCreate(url=URL, subpath="team-b"), admin)

    [still_a] = await skills.list_summaries(admin)
    assert still_a.id == skill.id and still_a.source_id is None  # untouched
    assert still_a.source_path == "team-a/skills/margin-audit"
    assert team_b.skill_count == 0
    [entry] = [e for e in team_b.last_report if e.name == "margin-audit"]
    assert entry.status == "skipped" and entry.issues[0].code == "W004"
    assert entry.path == "team-b/skills/margin-audit"


async def test_a_root_level_skill_is_reclaimable(agent_session, admin, host):
    """A repository that *is* one skill has its SKILL.md at the root, so its
    `source_path` is the empty string. That is a location like any other, and
    testing the path for truthiness rather than for None dropped exactly those
    skills from the reclaimable set — reconnecting imported a second copy."""
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    host.tree = {
        "SKILL.md": skill_md(
            "margin-audit", "Recompute margins. Use when margins look off."
        )
    }
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    [skill] = await skills.list_summaries(admin)
    assert skill.source_path == ""
    await sources.delete(source.id, admin)

    again = await sources.create(SkillSourceCreate(url=URL), admin)

    [reclaimed] = await skills.list_summaries(admin)
    assert reclaimed.id == skill.id and reclaimed.source_id == again.id


async def test_reconnecting_reclaims_across_a_ref_change(agent_session, admin, host):
    """Matching on the path rather than the full source identity is what lets
    a repository be reconnected on a different branch and still re-pin its own
    rows — the skill did not move, only the ref did."""
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL, ref="main"), admin)
    before = {s.name: s.id for s in await skills.list_summaries(admin)}
    await sources.delete(source.id, admin)

    again = await sources.create(SkillSourceCreate(url=URL, ref="v2"), admin)

    assert {s.name: s.id for s in await skills.list_summaries(admin)} == before
    assert {s.source_id for s in await skills.list_summaries(admin)} == {again.id}


async def test_a_repository_cannot_take_over_another_ones_detached_skill(
    agent_session, admin, host
):
    """Reclaim is scoped to the origin, not the name.

    A disconnected repository's skills keep their id and their agent bindings.
    If any repository that happened to use one of those names could claim the
    row, a sync would silently hand another repository's content to every
    agent bound to it — under the same id, with no undo. The name is taken;
    that is all a second repository gets to know about it.
    """
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    before = {s.name: s.id for s in await skills.list_summaries(admin)}
    await sources.delete(source.id, admin)

    # A different repository, with a skill of the same name.
    host.tree = {
        "skills/margin-audit/SKILL.md": skill_md(
            "margin-audit", "Something else entirely. Use when asked for it."
        )
    }
    host.revision = "ccc333"
    other = await sources.create(
        SkillSourceCreate(url="https://github.com/someone-else/skills"), admin
    )

    by_name = {s.name: s for s in await skills.list_summaries(admin)}
    assert by_name["margin-audit"].id == before["margin-audit"]
    assert by_name["margin-audit"].source_id is None  # still detached, untouched
    assert by_name["margin-audit"].source_revision == "aaa111"
    assert not by_name["margin-audit"].update_available
    assert other.skill_count == 0
    [entry] = [e for e in other.last_report if e.name == "margin-audit"]
    assert entry.status == "skipped" and entry.issues[0].code == "W004"


async def test_another_repositorys_sync_leaves_detached_skills_alone(
    agent_session, admin, host
):
    sources = SkillSourceService(agent_session)
    skills = SkillService(agent_session)
    source = await sources.create(SkillSourceCreate(url=URL), admin)
    await sources.delete(source.id, admin)

    host.tree = {
        "skills/pricing/SKILL.md": skill_md(
            "pricing", "Price a basket. Use when asked for a quote."
        )
    }
    other = await sources.create(
        SkillSourceCreate(url="https://github.com/acme/other"), admin
    )

    by_name = {s.name: s for s in await skills.list_summaries(admin)}
    assert set(by_name) == {"weekly-brief", "margin-audit", "pricing"}
    assert by_name["pricing"].source_id == other.id
    for name in ("weekly-brief", "margin-audit"):
        # Not this source's to claim, and so not this source's to flag.
        assert by_name[name].source_id is None
        assert not by_name[name].missing_upstream


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


async def test_preview_flags_a_name_the_library_has_already_taken(
    agent_session, admin, host
):
    """Whether a name is free is the library's answer, not the repository's.
    A preview that calls a skill importable and a sync that then skips it
    disagree about the same facts, and the admin only finds out afterwards."""
    await SkillService(agent_session).create(
        SkillSave(content=skill_markdown("margin-audit")), admin
    )
    preview = await SkillSourceService(agent_session).preview(
        SkillSourceCreate(url=URL)
    )

    by_name = {s.name: s for s in preview.skills}
    assert by_name["weekly-brief"].ok
    assert not by_name["margin-audit"].ok
    assert by_name["margin-audit"].issues[0].code == "W004"


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
