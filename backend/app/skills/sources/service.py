"""Skill sources: repositories the workspace syncs skills from.

Sync is the only step that reads the host, and it runs in a worker thread
(`skillkit` is synchronous). It makes each skill in the repository
*available*: a new skill becomes a library row pinned to the synced content;
a changed skill gets a stored version the owner adopts against a diff. Sync
never changes what an agent runs.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DomainValidationError, PermissionDeniedError
from app.service import BaseService
from app.skills.bundles import LIMITS, parse_skill, skill_file_from_bytes
from app.skills.models import SkillSourceDB
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
)
from app.skills.sources.repository import SkillSourceRepository
from app.users.models import UserDB, WorkspaceRole
from app.utils.encryption import decrypt_value, encrypt_value
from skillkit import (
    AuthenticationError,
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
        """Resolve without persisting anything — the "test before adding" step."""
        kind = _kind_for(data)
        resolved = await self._resolve(
            kind, data.url, data.ref, data.subpath, data.token
        )
        return SkillSourcePreview(
            kind=kind,
            name=_name_for(data.url),
            revision=resolved.revision,
            skills=[
                SkillSourcePreviewSkill(
                    name=skill.name,
                    description=skill.description,
                    path=skill.path,
                    container=skill.container,
                    script_count=sum(
                        1 for p in skill.bundle.files if p.startswith("scripts/")
                    ),
                    ok=skill.report.ok,
                    issues=_issues(skill),
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
        await self.db.flush()
        await self._sync_row(row)
        await self.db.refresh(row)
        return _response(row, user)

    async def update(
        self, source_id: UUID, data: SkillSourcePatch, user: UserDB
    ) -> SkillSourceResponse:
        row = await self._manageable(source_id, user)
        if data.ref is not None:
            row.ref = data.ref.strip()
        if data.subpath is not None:
            row.subpath = data.subpath.strip().strip("/") or None
        if data.clear_token:
            row.encrypted_token = None
        elif data.token:
            row.encrypted_token = encrypt_value(data.token)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return _response(row, user)

    async def delete(self, source_id: UUID, user: UserDB) -> None:
        """Its skills stay, as in-app skills: an agent must not lose a skill
        because an admin disconnected a repository."""
        row = await self._manageable(source_id, user)
        await self._skills.detach_from_source(row.id)
        await self.repository.delete(row)

    async def sync(self, source_id: UUID, user: UserDB) -> SkillSourceResponse:
        row = await self._manageable(source_id, user)
        await self._sync_row(row)
        await self.db.refresh(row)
        return _response(row, user)

    # -- the sync ------------------------------------------------------------------

    async def _sync_row(self, row: SkillSourceDB) -> None:
        token = decrypt_value(row.encrypted_token) if row.encrypted_token else None
        try:
            resolved = await self._resolve(
                row.kind, row.url, row.ref, row.subpath, token
            )
        except AuthenticationError as exc:
            return await self._failed(row, "auth", str(exc))
        except RevisionNotFound as exc:
            return await self._failed(row, "not_found", str(exc))
        except SourceUnavailable as exc:
            return await self._failed(row, "unavailable", str(exc))
        except (LimitExceeded, SkillkitValidationError) as exc:
            return await self._failed(row, "invalid", str(exc))

        existing = {s.name: s for s in await self._skills.list_for_source(row.id)}
        report: list[SkillSourceReportEntry] = []
        seen: set[str] = set()
        for skill in resolved.skills:
            issues = _issues(skill)
            if not skill.report.ok:
                report.append(
                    SkillSourceReportEntry(
                        path=skill.path, name=skill.name, issues=issues
                    )
                )
                continue
            if skill.name in seen:
                report.append(
                    SkillSourceReportEntry(
                        path=skill.path,
                        name=skill.name,
                        issues=[
                            SkillIssue(
                                code="W003",
                                severity="warning",
                                message="another skill in this repository already has this name",
                            )
                        ],
                    )
                )
                continue
            try:
                bundle = _app_bundle(skill)
            except DomainValidationError as exc:
                report.append(
                    SkillSourceReportEntry(
                        path=skill.path,
                        name=skill.name,
                        issues=[
                            SkillIssue(code="E000", severity="error", message=str(exc))
                        ],
                    )
                )
                continue
            seen.add(skill.name)
            digest = bundle_digest(bundle.file_bytes())
            current = existing.pop(skill.name, None)
            if current is None:
                created = await self._skills.create(
                    SkillCreateDB(
                        owner_id=row.owner_id,
                        name=bundle.name,
                        description=bundle.description,
                        content=bundle.content,
                        files=[f.model_dump(mode="json") for f in bundle.files],
                        digest=digest,
                        source_id=row.id,
                        source_path=skill.path,
                        source_revision=resolved.revision,
                    )
                )
                await self._skills.record_version(
                    created.id,
                    digest=digest,
                    revision=resolved.revision,
                    content=bundle.content,
                    files=[f.model_dump(mode="json") for f in bundle.files],
                )
                continue
            current.source_path = skill.path
            current.missing_upstream = False
            if digest != current.digest:
                await self._skills.record_version(
                    current.id,
                    digest=digest,
                    revision=resolved.revision,
                    content=bundle.content,
                    files=[f.model_dump(mode="json") for f in bundle.files],
                )
            else:
                current.source_revision = resolved.revision
            self.db.add(current)
        for leftover in existing.values():
            leftover.missing_upstream = True
            self.db.add(leftover)

        row.last_revision = resolved.revision
        row.last_synced_at = datetime.now(UTC)
        row.last_status = "ok"
        row.last_error = None
        row.last_report = [entry.model_dump(mode="json") for entry in report]
        row.skill_count = len(seen)
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

    async def _manageable(self, source_id: UUID, user: UserDB) -> SkillSourceDB:
        row = await self.get_or_404(source_id)
        if not _can_manage(user):
            raise PermissionDeniedError(
                "Only a workspace admin can change skill sources"
            )
        return row


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
