"""Skill sources: repositories the workspace syncs skills from.

Sync is the only step that reads the host, and it runs in a worker thread
(`skillkit` is synchronous). It makes each skill in the repository
*available*: a new skill becomes a library row pinned to the synced content;
a changed skill gets a stored version the owner adopts against a diff. Sync
never changes what an agent runs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.service import BaseService
from app.skills.bundles import LIMITS, parse_skill, skill_file_from_bytes
from app.skills.models import SkillDB, SkillSourceDB
from app.skills.repository import SkillRepository
from app.skills.schemas import (
    SkillBundle,
    SkillCreateDB,
    SkillIssue,
    SkillSourceCreate,
    SkillSourceKind,
    SkillSourcePatch,
    SkillSourcePreview,
    SkillSourcePreviewSkill,
    SkillSourceReportEntry,
    SkillSourceResponse,
    SkillSyncEntry,
    SkillSyncPlan,
    count_scripts,
)
from app.skills.sources.repository import SkillSourceRepository
from app.users.models import UserDB, WorkspaceRole
from app.utils.encryption import decrypt_value, encrypt_value
from skillkit import (
    AuthenticationError,
    EmptyRepository,
    GitHubSource,
    GitLabSource,
    LimitExceeded,
    ResolvedSource,
    RevisionNotFound,
    Skill,
    SourceUnavailable,
    StaticCredentials,
    ValidationError as SkillkitValidationError,
    bundle_digest,
)
from skillkit.model import SKILL_MD


class SkillSourceService(BaseService[SkillSourceDB, SkillSourceRepository]):
    not_found_message = "Skill source not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, SkillSourceRepository(db))
        self._skills = SkillRepository(db)

    # -- read ---------------------------------------------------------------------

    async def list(self, user: UserDB) -> list[SkillSourceResponse]:
        return [_response(row, user) for row in await self.repository.list_all()]

    async def get(self, source_id: UUID, user: UserDB) -> SkillSourceResponse:
        return _response(await self.get_or_404(source_id), user)

    # -- write --------------------------------------------------------------------

    async def preview(self, data: SkillSourceCreate) -> SkillSourcePreview:
        """Resolve without persisting anything — the "test before adding" step.

        Unlike a sync, this one *raises*: there is no row yet to record a
        status on, and the admin is waiting on an answer. Every failure the
        resolver can produce is a 400 about what they typed — an unhandled
        `SkillkitError` here is a 500, which is how a private repository came
        to look like an unsupported one.

        It also answers the question the *library* decides, not the
        repository: whether each name is free. A preview that calls a skill
        importable and a sync that then skips it disagree about the same
        facts, and the admin finds out after connecting.
        """
        kind = _kind_for(data)
        resolved = await self._resolve_or_400(
            kind, data.url, data.ref, data.subpath, data.token
        )
        library = await self._library_for(None, data.url)
        return SkillSourcePreview(
            kind=kind,
            name=_name_for(data.url),
            revision=resolved.revision,
            skills=[
                SkillSourcePreviewSkill(
                    name=skill.name,
                    description=skill.description,
                    # Repo-root-relative, like the path a sync stores, so the
                    # preview names a location the reader can actually open.
                    path=_full_path(data.subpath, skill.path),
                    container=skill.container,
                    script_count=sum(
                        1 for p in skill.bundle.files if p.startswith("scripts/")
                    ),
                    ok=skill.report.ok and skill.name not in library.taken,
                    issues=_issues(skill) + _taken_issue(skill.name, library),
                )
                for skill in resolved.skills
            ],
            issues=[SkillIssue(**i.__dict__) for i in resolved.issues],
        )

    async def create(
        self, data: SkillSourceCreate, user: UserDB
    ) -> SkillSourceResponse:
        kind = _kind_for(data)
        if await self.repository.get_by_url(data.url, data.ref, data.subpath):
            raise DomainValidationError(
                "This repository, ref and path are already a source"
            )
        row = SkillSourceDB(
            owner_id=user.id,
            name=_name_for(data.url),
            kind=kind,
            url=data.url,
            ref=data.ref,
            subpath=data.subpath,
            encrypted_token=encrypt_value(data.token) if data.token else None,
        )
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            # The lookup above cannot see a row another transaction has not
            # committed yet; `uq_skill_sources_identity` is what actually
            # holds. Same message either way.
            raise DomainValidationError(
                "This repository, ref and path are already a source"
            ) from exc
        await self._sync_row(row)
        await self.db.refresh(row)
        return _response(row, user)

    async def update(
        self, source_id: UUID, data: SkillSourcePatch, user: UserDB
    ) -> SkillSourceResponse:
        row = await self._manageable(source_id, user)
        # Same identity rule as `create`: a source *is* its (url, ref, path),
        # and an edit can collide with an existing one just as a create can.
        # Checked *before* the row is touched — assigning first makes the
        # lookup autoflush the pending UPDATE, and the database raises the
        # collision before this has a chance to phrase it.
        ref = data.ref.strip() if data.ref is not None else row.ref
        subpath = (
            (data.subpath.strip().strip("/") or None)
            if data.subpath is not None
            else row.subpath
        )
        clash = await self.repository.get_by_url(row.url, ref, subpath)
        if clash is not None and clash.id != row.id:
            raise DomainValidationError(
                "Another source already tracks this repository, ref and path"
            )
        row.ref = ref
        row.subpath = subpath
        if data.clear_token:
            row.encrypted_token = None
        elif data.token:
            row.encrypted_token = encrypt_value(data.token)
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            # Same race as `create`: the preflight above cannot see a row
            # another transaction has not committed yet.
            raise DomainValidationError(
                "Another source already tracks this repository, ref and path"
            ) from exc
        await self.db.refresh(row)
        return _response(row, user)

    async def delete(self, source_id: UUID, user: UserDB) -> None:
        """Its skills stay, detached: an agent must not lose a skill because
        an admin disconnected a repository, and everything those skills need
        — files and `scripts/` included — is already in their rows.

        Detached is not "written here": the content still came from the
        repository, so the library keeps it read-only rather than handing it
        to an editor that cannot write files. Removing one from the library
        stays allowed — that is not editing. Connecting the repository again
        re-pins the same rows (`_classify`), so a disconnect is reversible
        and never doubles the library."""
        row = await self._manageable(source_id, user, lock=True)
        await self._skills.detach_from_source(row.id)
        await self.repository.delete(row)

    async def sync(self, source_id: UUID, user: UserDB) -> SkillSourceResponse:
        row = await self._manageable(source_id, user, lock=True)
        await self._sync_row(row)
        await self.db.refresh(row)
        return _response(row, user)

    async def _resolve_or_400(
        self,
        kind: SkillSourceKind,
        url: str,
        ref: str,
        subpath: str | None,
        token: str | None,
    ) -> ResolvedSource:
        """Resolve for a *request*: every failure is a 400 about what the
        caller asked for. `_sync_row` does not use this — it records a status
        on the row instead of raising, because nobody is waiting on it."""
        try:
            return await self._resolve(kind, url, ref, subpath, token)
        except EmptyRepository as exc:
            raise DomainValidationError(f"{exc}. {_EMPTY_HINT}") from exc
        except (AuthenticationError, RevisionNotFound) as exc:
            raise DomainValidationError(f"{exc}.{_access_hint(bool(token))}") from exc
        except (SourceUnavailable, LimitExceeded, SkillkitValidationError) as exc:
            raise DomainValidationError(str(exc)) from exc

    async def plan(self, source_id: UUID, user: UserDB) -> SkillSyncPlan:
        """What syncing would do, without doing any of it.

        Reads the repository exactly as a sync would and classifies every
        skill against what the library already holds. Writes nothing, so it
        can be run to decide whether to sync at all.
        """
        row = await self._manageable(source_id, user)
        token = decrypt_value(row.encrypted_token) if row.encrypted_token else None
        resolved = await self._resolve_or_400(
            row.kind, row.url, row.ref, row.subpath, token
        )
        decisions, _report = _classify(resolved, await self._library(row), row.subpath)
        return SkillSyncPlan(
            revision=resolved.revision,
            current_revision=row.last_revision,
            entries=[
                SkillSyncEntry(
                    name=d.name,
                    path=d.path,
                    status=d.status,
                    script_count=count_scripts(d.bundle.files) if d.bundle else 0,
                    issues=d.issues,
                )
                for d in decisions
            ],
        )

    # -- the sync ------------------------------------------------------------------

    async def _sync_row(self, row: SkillSourceDB) -> None:
        token = decrypt_value(row.encrypted_token) if row.encrypted_token else None
        try:
            resolved = await self._resolve(
                row.kind, row.url, row.ref, row.subpath, token
            )
        except EmptyRepository as exc:
            return await self._failed(row, "empty", f"{exc}. {_EMPTY_HINT}")
        except AuthenticationError as exc:
            return await self._failed(
                row, "auth", f"{exc}.{_access_hint(token is not None)}"
            )
        except RevisionNotFound as exc:
            return await self._failed(
                row, "not_found", f"{exc}.{_access_hint(token is not None)}"
            )
        except SourceUnavailable as exc:
            return await self._failed(row, "unavailable", str(exc))
        except (LimitExceeded, SkillkitValidationError) as exc:
            return await self._failed(row, "invalid", str(exc))

        decisions, report = _classify(resolved, await self._library(row), row.subpath)
        # Decisions the unique index refused after `_classify` had cleared
        # them — a concurrent sync of another repository took the name first.
        taken: list[_Decision] = []

        for decision in decisions:
            # `assert` would be the obvious narrowing here, but it is compiled
            # out under -O and static analysis rightly flags it. `_incoming`
            # states the invariant once and raises for real if it is ever broken.
            if decision.status == "skipped":
                continue

            if decision.status == "new":
                bundle, digest = _incoming(decision)
                # In a SAVEPOINT: `_classify` read the taken names a moment
                # ago, and the lock this sync holds is on its *own* source
                # row, so a concurrent sync of a *different* repository can
                # take the name in between. The unique index is what actually
                # decides, and losing that race is the ordinary name-taken
                # outcome — not a reason to fail a sync that has already
                # imported half a repository. The savepoint is what lets the
                # rest of the loop keep using the session afterwards.
                try:
                    async with self.db.begin_nested():
                        created = await self._skills.create(
                            SkillCreateDB(
                                owner_id=row.owner_id,
                                name=bundle.name,
                                description=bundle.description,
                                content=bundle.content,
                                files=[f.model_dump(mode="json") for f in bundle.files],
                                digest=digest,
                                source_id=row.id,
                                source_url=row.url,
                                source_path=decision.path,
                                source_revision=resolved.revision,
                            )
                        )
                except IntegrityError:
                    taken.append(decision)
                    continue
                await self._skills.record_version(
                    created.id,
                    digest=digest,
                    revision=resolved.revision,
                    content=bundle.content,
                    files=[f.model_dump(mode="json") for f in bundle.files],
                )
                continue

            current = decision.current
            if current is None:
                raise RuntimeError(
                    f"{decision.name}: a '{decision.status}' decision must carry a row"
                )
            if decision.status == "gone":
                current.missing_upstream = True
                self.db.add(current)
                continue

            # `source_id` for the rows this sync re-pins — a skill this same
            # repository left detached by an earlier disconnect. `source_url`
            # with it, so a source that moved host (an org rename, a mirror)
            # re-pins the row to where it is read from now.
            current.source_id = row.id
            current.source_url = row.url
            current.source_path = decision.path
            current.missing_upstream = False
            if decision.status == "updated":
                bundle, digest = _incoming(decision)
                # Recorded as *available*, never applied: what an agent runs
                # changes only when someone adopts it.
                await self._skills.record_version(
                    current.id,
                    digest=digest,
                    revision=resolved.revision,
                    content=bundle.content,
                    files=[f.model_dump(mode="json") for f in bundle.files],
                )
            else:  # unchanged
                current.source_revision = resolved.revision
            self.db.add(current)

        row.last_revision = resolved.revision
        row.last_synced_at = datetime.now(UTC)
        row.last_status = "ok"
        row.last_error = None
        # Every decision, not only the failures. A sync is the one operation
        # here that changes the library with nobody watching — the plan says
        # what it will do, and this is the only record of what it did.
        # A name lost to a concurrent sync reads exactly like one that was
        # already taken when `_classify` ran — same status, same issue, same
        # remedy. Restated in both the report and the decisions so
        # `skill_count` below counts what the library actually holds.
        for decision in taken:
            decision.status = "skipped"
            for entry in report:
                if entry.name == decision.name and entry.path == decision.path:
                    entry.status = "skipped"
                    entry.issues = [_NAME_TAKEN]
        row.last_report = [entry.model_dump(mode="json") for entry in report]
        # What the repository currently contributes: present upstream and
        # valid. A skipped skill was never counted, and a `gone` one is no
        # longer there — counting it would keep a deleted skill in the total.
        row.skill_count = sum(
            1 for d in decisions if d.status in ("new", "updated", "unchanged")
        )
        self.db.add(row)
        await self.db.flush()

    async def _resolve(
        self,
        kind: SkillSourceKind,
        url: str,
        ref: str,
        subpath: str | None,
        token: str | None,
    ) -> ResolvedSource:
        cls = GitLabSource if kind == SkillSourceKind.gitlab else GitHubSource
        try:
            source = cls(
                url,
                ref=ref,
                subpath=subpath,
                credentials=StaticCredentials(token),
                limits=LIMITS,
            )
        except ValueError as exc:
            raise DomainValidationError(str(exc)) from exc
        return await asyncio.to_thread(source.resolve)

    async def _failed(self, row: SkillSourceDB, status: str, error: str) -> None:
        """A failed sync leaves everything the previous one wrote intact and
        surfaces on the source, not on its skills."""
        row.last_synced_at = datetime.now(UTC)
        row.last_status = status
        row.last_error = error[:2000]
        self.db.add(row)
        await self.db.flush()

    async def _library(self, row: SkillSourceDB) -> LibraryIndex:
        return await self._library_for(row.id, row.url)

    async def _library_for(self, source_id: UUID | None, url: str) -> LibraryIndex:
        """The library as a sync of this repository sees it — three queries,
        no matter how many skills the repository holds. `source_id` is None
        for a repository that is not connected yet (`preview`), which owns no
        rows but can still reclaim the ones it left behind.
        """
        mine = (
            {s.name: s for s in await self._skills.list_for_source(source_id)}
            if source_id is not None
            else {}
        )
        # Keyed by `source_path`, not by name — a detached row is reclaimed
        # because it is *the same skill*, and what says so is where it sits in
        # the repository. Keying on the name would let one subpath of a
        # monorepo claim another's row: two sources on one URL with different
        # subpaths see the same names, and the URL alone cannot tell them
        # apart. `source_path` is repo-root-relative (`_full_path`), so the
        # subpath is part of it and this is a true identity.
        claimed = {s.id for s in mine.values()}
        reclaimable = {
            s.source_path: s
            for s in await self._skills.list_reclaimable(url)
            if s.id not in claimed and s.source_path
        }
        ours = {s.id for s in (*mine.values(), *reclaimable.values())}
        return LibraryIndex(
            mine=mine,
            reclaimable=reclaimable,
            taken=frozenset(
                name
                for skill_id, name in await self._skills.list_all_names()
                if skill_id not in ours
            ),
        )

    async def _manageable(
        self, source_id: UUID, user: UserDB, *, lock: bool = False
    ) -> SkillSourceDB:
        """The source, and the right to change it.

        `lock` takes the row for the rest of the transaction. Two syncs of one
        source run the same classification against the same library and both
        decide a skill is `new`; whichever loses the unique index on the name
        then fails the whole request. The lock makes the second wait and
        classify against what the first wrote, which is `unchanged`.
        """
        row = (
            await self.repository.get_for_update(source_id)
            if lock
            else await self.repository.get(source_id)
        )
        if row is None:
            raise NotFoundError(self.not_found_message)
        if not _can_manage(user):
            raise PermissionDeniedError(
                "Only a workspace admin can change skill sources"
            )
        return row


_EMPTY_HINT = (
    "Push a skill to it first — auxilia reads "
    "skills/<name>/SKILL.md, a category folder one level deeper, or a "
    "SKILL.md at the root."
)


def _access_hint(has_token: bool) -> str:
    """Why a repository that exists can still read as "not found".

    GitHub and GitLab answer 404, not 403, for a private repository the
    caller cannot see — revealing that it exists would itself leak something.
    So the resolver genuinely cannot tell a typo from a missing credential,
    and the bare message ("repository, ref or path not found") reads as
    "private repositories are not supported". Name the likelier cause.
    """
    if has_token:
        return (
            " If it is private, check the token still has read access to its "
            "contents and has not expired."
        )
    return " If it is private, add an access token with read access to its contents."


def _kind_for(data: SkillSourceCreate) -> SkillSourceKind:
    if data.kind is not None:
        return data.kind
    host = urlsplit(data.url).netloc.lower()
    if host in ("github.com", "www.github.com"):
        return SkillSourceKind.github
    if host in ("gitlab.com", "www.gitlab.com"):
        return SkillSourceKind.gitlab
    raise DomainValidationError(
        "Choose the host type (GitHub or GitLab) for a self-hosted instance"
    )


def _name_for(url: str) -> str:
    return urlsplit(url).path.strip("/").removesuffix(".git")[:120] or url[:120]


@dataclass(frozen=True)
class LibraryIndex:
    """What the library already holds, as one sync needs to see it.

    Three answers to the same question — "is this name already spoken for?" —
    and they are not the same answer, which is why they are three fields and
    not one dictionary:

    - `mine` — this source's own rows, by name. A name found here is the
      skill this sync updates, and a name *not* found again upstream is the
      one it marks `gone`.
    - `reclaimable` — rows this same repository left behind when it was
      disconnected (`SkillRepository.list_reclaimable`), **by repo-root
      `source_path`**, not by name. A path found here is claimed: the row is
      re-pinned, keeping its id and every agent binding. The path is the
      identity because the URL alone is not one — two sources can share a URL
      with different `subpath`s, see the same skill names, and would
      otherwise claim each other's rows.
    - `taken` — every other name in the library: another repository's skills,
      skills written in the app, and skills a *different* repository left
      behind. A name found here is not this sync's to touch, and the incoming
      skill is skipped and reported rather than imported as a duplicate.
    """

    mine: dict[str, SkillDB]
    reclaimable: dict[str, SkillDB]
    taken: frozenset[str]


@dataclass
class _Decision:
    """What a sync would do to one skill, decided before anything is written
    so the same call can answer "what would change?" and "change it"."""

    name: str
    path: str
    status: str  # new | updated | unchanged | gone | skipped
    issues: list[SkillIssue]
    bundle: SkillBundle | None = None
    digest: str | None = None
    current: SkillDB | None = None


def _incoming(decision: _Decision) -> tuple[SkillBundle, str]:
    """The content a `new` or `updated` decision carries.

    `_classify` always fills both for those two statuses; this turns that
    invariant into a real failure rather than an `assert` that disappears
    under -O and reads as a security finding to static analysis.
    """
    if decision.bundle is None or decision.digest is None:
        raise RuntimeError(
            f"{decision.name}: a '{decision.status}' decision must carry a bundle"
        )
    return decision.bundle, decision.digest


def _full_path(subpath: str | None, path: str) -> str:
    """A skill's location in the *repository*, not under the source's subpath.

    `discover` strips the subpath before walking, so `Skill.path` is relative
    to it: `team-a/skills/x` and `team-b/skills/x` both arrive as
    `skills/x`. Stored as-is, two sources on one repository would record the
    same `source_path` for different skills, and a reclaim keyed on it would
    hand one subpath's row to the other. Putting the subpath back makes
    `source_path` a location anyone can resolve in the repository, and makes
    (`source_url`, `source_path`) a real identity.
    """
    prefix = (subpath or "").strip("/")
    path = path.strip("/")
    return f"{prefix}/{path}".strip("/") if prefix else path


def _classify(
    resolved: ResolvedSource, library: LibraryIndex, subpath: str | None = None
) -> tuple[list[_Decision], list[SkillSourceReportEntry]]:
    """Compare what the repository holds against what the library holds.

    Pure: it reads the resolved source and the current rows and touches
    neither. `_sync_row` applies the result and `plan` returns it, so the two
    can never disagree about what a sync does.
    """
    remaining = dict(library.mine)
    unclaimed = dict(library.reclaimable)
    decisions: list[_Decision] = []
    report: list[SkillSourceReportEntry] = []
    seen: set[str] = set()

    def record(
        name: str, path: str, status: str, issues: list[SkillIssue]
    ) -> SkillSourceReportEntry:
        return SkillSourceReportEntry(
            path=path, name=name, status=status, issues=issues
        )

    def skip(skill: Skill, issues: list[SkillIssue]) -> None:
        path = _full_path(subpath, skill.path)
        report.append(record(skill.name, path, "skipped", issues))
        decisions.append(
            _Decision(name=skill.name, path=path, status="skipped", issues=issues)
        )
        # It is still upstream, just unusable this time round. Leaving it in
        # `remaining` made the same sync mark it `gone` as well, so the
        # library claimed the skill had been deleted from the repository.
        remaining.pop(skill.name, None)

    for skill in resolved.skills:
        if not skill.report.ok:
            skip(skill, _issues(skill))
            continue
        if skill.name in seen:
            skip(
                skill,
                [
                    SkillIssue(
                        code="W003",
                        severity="warning",
                        message="another skill in this repository already has this name",
                    )
                ],
            )
            continue
        if skill.name in library.taken:
            # The library is one namespace and this name is somebody else's:
            # another repository's skill, one written in the app, or one a
            # *different* repository left behind. Importing it anyway would
            # put two identically-named rows in front of every reader and
            # defer the collision to the agent's config save, where it can no
            # longer be resolved. Reported, and left for a human to settle.
            skip(skill, [_NAME_TAKEN])
            continue
        try:
            bundle = _app_bundle(skill)
        except DomainValidationError as exc:
            skip(skill, [SkillIssue(code="E000", severity="error", message=str(exc))])
            continue

        seen.add(skill.name)
        digest = bundle_digest(bundle.file_bytes())
        path = _full_path(subpath, skill.path)
        # `mine` by name (that is what makes a skill missing upstream read as
        # `gone`), `reclaimable` by path (that is what makes it the same skill).
        current = remaining.pop(skill.name, None) or unclaimed.pop(path, None)
        status = (
            "new"
            if current is None
            else "updated"
            if digest != current.digest
            else "unchanged"
        )
        report.append(record(skill.name, path, status, _issues(skill)))
        decisions.append(
            _Decision(
                name=skill.name,
                path=path,
                status=status,
                issues=_issues(skill),
                bundle=bundle,
                digest=digest,
                current=current,
            )
        )

    for name, leftover in remaining.items():
        path = leftover.source_path or ""
        report.append(record(name, path, "gone", []))
        decisions.append(
            _Decision(name=name, path=path, status="gone", issues=[], current=leftover)
        )
    return decisions, report


def _app_bundle(skill: Skill) -> SkillBundle:
    text = skill.bundle.files[SKILL_MD].decode("utf-8-sig")
    files = [
        skill_file_from_bytes(path, content)
        for path, content in skill.bundle.files.items()
        if path != SKILL_MD
    ]
    return parse_skill(text, files)


def _issues(skill: Skill) -> list[SkillIssue]:
    return [SkillIssue(**issue.__dict__) for issue in skill.report.issues]


# One wording for "the library already has this name", used by the preview
# (before connecting) and by `_classify` (at every sync), so the two never
# describe the same refusal differently.
_NAME_TAKEN = SkillIssue(
    code="W004",
    severity="warning",
    message=(
        "a different skill in the library already has this name — rename it "
        "here or remove the other one, then sync again"
    ),
)


def _taken_issue(name: str, library: LibraryIndex) -> list[SkillIssue]:
    return [_NAME_TAKEN] if name in library.taken else []


def _can_manage(user: UserDB) -> bool:
    return user.role == WorkspaceRole.admin


def _response(row: SkillSourceDB, user: UserDB) -> SkillSourceResponse:
    return SkillSourceResponse(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        kind=row.kind,
        url=row.url,
        ref=row.ref,
        subpath=row.subpath,
        has_token=row.encrypted_token is not None,
        last_revision=row.last_revision,
        last_synced_at=row.last_synced_at,
        last_status=row.last_status,
        last_error=row.last_error,
        last_report=[
            SkillSourceReportEntry.model_validate(e) for e in row.last_report or []
        ],
        skill_count=row.skill_count,
        can_manage=_can_manage(user),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_skill_source_service(db: AsyncSession = Depends(get_db)) -> SkillSourceService:
    return SkillSourceService(db)
