from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    AlreadyExistsError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    StaleRevisionError,
)
from app.service import BaseService
from app.skills.bundles import parse_skill
from app.skills.models import SkillDB, SkillImageDB, SkillVersionDB
from app.skills.repository import SkillRepository
from app.skills.schemas import (
    AgentSkillResponse,
    SkillAgentRef,
    SkillBundle,
    SkillCreateDB,
    SkillDiffResponse,
    SkillFile,
    SkillFileChange,
    SkillResponse,
    SkillSave,
    SkillSummary,
    SkillVersionInfo,
    count_scripts,
)
from app.teams.repository import TeamRepository
from app.users.models import UserDB, WorkspaceRole
from app.utils.images import ProcessedImage
from app.visibility import (
    ResourceVisibility,
    audience_contains,
    is_resource_visible,
    is_resource_visible_to_identity,
    validate_visibility,
)
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.repository import WorkspaceRepository
from skillkit import Bundle, bundle_digest, diff_bundles


class SkillService(BaseService[SkillDB, SkillRepository]):
    """The skill library, and which agents each skill is enabled on.

    Every workspace user can read and use every skill; only its owner or a
    workspace admin can change or delete it. Enabling a skill on an agent is
    part of the agent's config save, so the *agent* permission gate
    (`AgentService.set_config`) is what protects `set_for_agent`.
    """

    not_found_message = "Skill not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(db, SkillRepository(db, workspace_id))
        self.workspace_id = workspace_id
        self.teams = TeamRepository(db)

    # -- the library ---------------------------------------------------------

    async def list_summaries(self, user: UserDB) -> list[SkillSummary]:
        # Batch the library, team links, and agent bindings; the visibility
        # projection is also loaded once, never once per skill.
        rows = await self.repository.list_summaries()
        team_ids = await self.repository.list_team_ids_for_skills(
            [row.id for row in rows if row.visibility == ResourceVisibility.teams]
        )
        by_skill: dict[UUID, list[SkillAgentRef]] = defaultdict(list)
        for binding in await self.repository.list_agents_by_skill(
            user_id=user.id,
            is_admin=user.role == WorkspaceRole.admin,
            team_id=user.team_id,
        ):
            by_skill[binding.skill_id].append(
                SkillAgentRef(
                    **{k: v for k, v in binding._mapping.items() if k != "skill_id"}
                )
            )
        return [
            SkillSummary(
                **{
                    k: v
                    for k, v in row._mapping.items()
                    if k not in {"latest_digest", "agent_count"}
                },
                team_ids=team_ids.get(row.id, []),
                agents=by_skill.get(row.id, []),
                agent_count=len(by_skill.get(row.id, [])),
                can_edit=_can_edit(row.owner_id, user)
                and not _is_sourced(row.source_revision),
                can_manage=_can_edit(row.owner_id, user),
                update_available=_update_available(row.digest, row.latest_digest),
            )
            for row in rows
            if is_resource_visible(
                visibility=row.visibility,
                owner_id=row.owner_id,
                team_ids=set(team_ids.get(row.id, [])),
                user=user,
            )
        ]

    async def get(self, skill_id: UUID, user: UserDB) -> SkillResponse:
        row = await self.repository.get_scoped(skill_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        await self._ensure_visible(row, user)
        return await self._response(row, user)

    async def create(self, data: SkillSave, user: UserDB) -> SkillResponse:
        _reject_files(data)
        bundle = parse_skill(data.content, data.files)
        visibility = data.visibility or ResourceVisibility.workspace
        team_ids = data.team_ids or []
        await self._validate_teams(team_ids)
        validate_visibility(visibility, team_ids)
        await self._name_is_free(bundle.name)
        try:
            if self.workspace_id is None:
                raise RuntimeError("workspace_id is required to create a skill")
            row = await self.repository.create(
                SkillCreateDB(
                    workspace_id=self.workspace_id,
                    owner_id=user.id,
                    visibility=visibility,
                    group=data.group,
                    emoji=data.emoji,
                    color=data.color,
                    **_columns(bundle),
                )
            )
            if team_ids:
                await self.repository.set_team_ids(row.id, team_ids)
        except IntegrityError as exc:
            raise _name_taken(bundle.name) from exc
        return await self._response(row, user)

    async def update(
        self, skill_id: UUID, data: SkillSave, user: UserDB
    ) -> SkillResponse:
        bundle = parse_skill(data.content, data.files)
        row = await self._editable(skill_id, user)
        was_team_scoped = row.visibility == ResourceVisibility.teams
        visibility = data.visibility or row.visibility
        team_ids = (
            data.team_ids
            if data.team_ids is not None
            else (
                await self.repository.list_team_ids(row.id) if was_team_scoped else []
            )
        )
        await self._validate_teams(team_ids)
        validate_visibility(visibility, team_ids)
        if data.visibility is not None or data.team_ids is not None:
            await self._ensure_bound_agent_scopes(row, visibility, team_ids)
        if data.revision != row.revision:
            raise StaleRevisionError(
                "This skill changed since you opened it. Reload it before saving."
            )
        if _is_sourced(row.source_revision):
            current = row.to_bundle()
            if bundle.content != current.content or bundle.files != current.files:
                raise DomainValidationError(_repository_owns(row))
            row.sqlmodel_update(
                {
                    "group": data.group,
                    "emoji": data.emoji,
                    "color": data.color,
                    "visibility": visibility,
                }
            )
            if data.team_ids is not None:
                await self.repository.set_team_ids(row.id, team_ids)
            return await self._response(await self._flush(row), user)
        _reject_files(data)
        if bundle.name != row.name:
            await self._name_is_free(bundle.name)
            if await self.repository.is_attached(row.id):
                # Agents address a skill by name and share one namespace per
                # graph; renaming in place could collide with, or hide, a live
                # catalog.
                raise DomainValidationError(
                    "Disable this skill on every agent before renaming it"
                )
        row.sqlmodel_update(
            {
                **_columns(bundle),
                "group": data.group,
                "emoji": data.emoji,
                "color": data.color,
                "visibility": visibility,
                "revision": row.revision + 1,
            }
        )
        if data.team_ids is not None:
            await self.repository.set_team_ids(row.id, team_ids)
        return await self._response(await self._flush(row), user)

    async def get_image(self, skill_id: UUID, user: UserDB) -> SkillImageDB:
        row = await self.repository.get_scoped(skill_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        await self._ensure_visible(row, user)
        image = await self.repository.get_image(skill_id)
        if image is None:
            raise NotFoundError("Skill image not found")
        return image

    async def set_image(
        self, skill_id: UUID, user: UserDB, image: ProcessedImage
    ) -> UUID:
        await self._editable(skill_id, user)
        revision = uuid4()
        await self.repository.set_image(
            skill_id,
            data=image.data,
            media_type=image.media_type,
            sha256=image.sha256,
            revision=revision,
        )
        return revision

    async def delete_image(self, skill_id: UUID, user: UserDB) -> None:
        await self._editable(skill_id, user)
        await self.repository.delete_image(skill_id)

    async def delete(self, skill_id: UUID, user: UserDB) -> None:
        # Deleting is not editing: a sourced skill, detached or not, is
        # removed from the library here like any other. What the repository
        # owns is the *content* — nothing here can write it — and dropping a
        # row the repository still has is undone by a sync.
        row = await self._editable(skill_id, user)
        if await self.repository.is_attached(row.id):
            raise DomainValidationError(
                "Disable this skill on every agent before deleting it"
            )
        await self.repository.delete(row)

    # -- sourced skills: the version waiting upstream -------------------------

    async def diff(self, skill_id: UUID, user: UserDB) -> SkillDiffResponse:
        """What adopting the newest synced version would change (skillkit's
        semantic diff). `unchanged` when nothing newer is stored."""
        row = await self.repository.get_scoped(skill_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        await self._ensure_visible(row, user)
        current = Bundle(row.to_bundle().file_bytes())
        version = await self.repository.latest_version(row.id)
        if version is None or version.digest == (row.digest or current.digest):
            return SkillDiffResponse(
                name=row.name,
                status="unchanged",
                old_digest=row.digest or current.digest,
                new_digest=row.digest or current.digest,
                old_revision=row.source_revision,
                new_revision=row.source_revision,
                categories=[],
                description_changed=False,
                instructions_changed=False,
                scripts_changed=False,
                requirements_changed=False,
                files=[],
            )
        new = Bundle(_version_bundle(version).file_bytes())
        diff = diff_bundles(row.name, current, new)
        return SkillDiffResponse(
            name=row.name,
            status=diff.status,
            old_digest=diff.old_digest,
            new_digest=diff.new_digest,
            old_revision=row.source_revision,
            new_revision=version.revision,
            categories=list(diff.categories),
            description_changed=diff.description_changed,
            instructions_changed=diff.instructions_changed,
            scripts_changed=diff.scripts_changed,
            requirements_changed=diff.requirements_changed,
            files=[SkillFileChange(**change.__dict__) for change in diff.files],
        )

    async def adopt(self, skill_id: UUID, user: UserDB) -> SkillResponse:
        """Make the newest synced version the one agents run. Explicit on
        purpose: sync only makes versions *available*."""
        row = await self._editable(skill_id, user)
        version = await self.repository.latest_version(row.id)
        if version is None or version.digest == row.digest:
            return await self._response(row, user)
        bundle = _version_bundle(version)
        if bundle.name != row.name:
            # Upstream renamed it. The library is one namespace, so the new
            # name has to be free here too — an adopt is a save like any other.
            await self._name_is_free(bundle.name)
            if await self.repository.is_attached(row.id):
                raise DomainValidationError(
                    "This version renames the skill; disable it on every agent "
                    "before adopting"
                )
        row.sqlmodel_update(
            {
                **_columns(bundle),
                "revision": row.revision + 1,
                "source_revision": version.revision,
                "missing_upstream": False,
            }
        )
        return await self._response(await self._flush(row), user)

    async def _name_is_free(self, name: str) -> None:
        """The library is one namespace. Refused here rather than at the
        agent's config save: an agent addresses a skill by name and a graph
        cannot hold two of one name, and by the time the config save says so
        the remedy it offers ("rename one of them") may not exist — a skill
        synced from a repository is not renameable here at all.

        The unique index is what actually holds; this is the wording. Two
        requests naming the same skill at once both pass this lookup — neither
        can see the other's uncommitted row — so `_flush` catches the index
        refusing the loser and says the same thing rather than 500ing.
        """
        if await self.repository.get_by_name(name) is not None:
            raise _name_taken(name)

    async def _flush(self, row: SkillDB) -> SkillDB:
        """Persist a save, turning a lost name race into the 409 it is."""
        self.db.add(row)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise _name_taken(row.name) from exc
        await self.db.refresh(row)
        return row

    async def _editable(self, skill_id: UUID, user: UserDB) -> SkillDB:
        row = await self.repository.get_for_update(skill_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        if not _can_edit(row.owner_id, user):
            raise PermissionDeniedError(
                "Only the skill's owner or a workspace admin can change it"
            )
        return row

    async def _ensure_visible(self, row: SkillDB, user: UserDB) -> None:
        team_ids = (
            set(await self.repository.list_team_ids(row.id))
            if row.visibility == ResourceVisibility.teams
            else set()
        )
        if not is_resource_visible(
            visibility=row.visibility,
            owner_id=row.owner_id,
            team_ids=team_ids,
            user=user,
        ):
            raise NotFoundError(self.not_found_message)

    async def _validate_teams(self, team_ids: list[UUID]) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required")
        for team_id in set(team_ids):
            if (
                await self.teams.get_in_workspace_for_key_share(
                    team_id, self.workspace_id
                )
                is None
            ):
                raise NotFoundError("Team not found")

    async def _ensure_bound_agent_scopes(
        self, skill: SkillDB, visibility, team_ids: list[UUID]
    ) -> None:
        from app.agents.core.repository import AgentRepository

        agents = AgentRepository(self.db, self.workspace_id)
        for agent in await self.repository.list_bound_agents(skill.id):
            parent_team_ids = (
                set(await agents.get_team_ids(agent.id))
                if agent.visibility == ResourceVisibility.teams
                else set()
            )
            if not audience_contains(
                parent_visibility=agent.visibility,
                parent_owner_id=agent.owner_id,
                parent_team_ids=parent_team_ids,
                child_visibility=visibility,
                child_owner_id=skill.owner_id,
                child_team_ids=set(team_ids),
            ):
                raise DomainValidationError(
                    f"Skill scope is incompatible with agent '{agent.name}'"
                )
            await self._ensure_skill_visible_to_grantees(
                agents, agent.id, skill.owner_id, visibility, set(team_ids)
            )

    async def _ensure_skill_visible_to_grantees(
        self,
        agents,
        agent_id: UUID,
        skill_owner_id: UUID,
        visibility,
        team_ids: set[UUID],
    ) -> None:
        if self.workspace_id is None:
            return
        workspaces = WorkspaceRepository(self.db)
        for grant in await agents.get_permissions(agent_id):
            membership = await workspaces.get_membership(
                self.workspace_id, grant.user_id
            )
            if membership is not None and not is_resource_visible_to_identity(
                visibility=visibility,
                owner_id=skill_owner_id,
                team_ids=team_ids,
                user_id=grant.user_id,
                is_admin=membership.role == WorkspaceRole.admin,
                team_id=membership.team_id,
            ):
                raise DomainValidationError(
                    "Skill is not visible to every explicitly granted agent user"
                )

    async def _response(self, row: SkillDB, user: UserDB) -> SkillResponse:
        bundle = row.to_bundle()
        agents = [
            SkillAgentRef(**agent._mapping)
            for agent in await self.repository.list_agents_using(
                row.id,
                user_id=user.id,
                is_admin=user.role == WorkspaceRole.admin,
                team_id=user.team_id,
            )
        ]
        latest = await self.repository.latest_version(row.id) if row.source_id else None
        available = (
            SkillVersionInfo(
                digest=latest.digest,
                revision=latest.revision,
                discovered_at=latest.created_at,
            )
            if latest is not None and _update_available(row.digest, latest.digest)
            else None
        )
        source = (
            await self.repository.get_source(row.source_id) if row.source_id else None
        )
        return SkillResponse(
            id=row.id,
            owner_id=row.owner_id,
            visibility=row.visibility,
            team_ids=(
                await self.repository.list_team_ids(row.id)
                if row.visibility == ResourceVisibility.teams
                else []
            ),
            name=bundle.name,
            description=bundle.description,
            group=row.group,
            emoji=row.emoji,
            color=row.color,
            image_revision=row.image_revision,
            revision=row.revision,
            file_count=len(bundle.files),
            script_count=count_scripts(bundle.files),
            agent_count=len(agents),
            updated_at=row.updated_at,
            can_edit=_can_edit(row.owner_id, user)
            and not _is_sourced(row.source_revision),
            can_manage=_can_edit(row.owner_id, user),
            source_id=row.source_id,
            source_name=source.name if source else None,
            source_url=row.source_url,
            source_path=row.source_path,
            source_revision=row.source_revision,
            digest=row.digest,
            update_available=available is not None,
            missing_upstream=row.missing_upstream,
            content=bundle.content,
            files=bundle.files,
            agents=agents,
            available=available,
        )

    # -- agent bindings ------------------------------------------------------

    async def list_for_agent(self, agent_id: UUID) -> list[AgentSkillResponse]:
        return [
            AgentSkillResponse(**row._mapping)
            for row in await self.repository.list_attached(agent_id)
        ]

    async def set_for_agent(self, agent_id: UUID, skill_ids: Iterable[UUID]) -> None:
        """Whole-set replace of an agent's skills, from the config save.

        There is no graph-wide name check here, and there is nothing for one
        to catch: the library is one namespace, so two *different* skills of
        one name do not exist to be enabled together. Enabling a skill is a
        binding, and a binding cannot create a collision the library already
        refused. `SkillsBackend` keeps the last word at run time, for data
        that changed under a run.
        """
        wanted = set(skill_ids)
        if wanted - await self.repository.list_existing_ids(wanted):
            raise NotFoundError(self.not_found_message)
        if wanted:
            from app.agents.core.repository import AgentRepository

            agents = AgentRepository(self.db, self.workspace_id)
            agent = await agents.get_scoped(agent_id)
            if agent is None:
                raise NotFoundError("Agent not found")
            agent_team_ids = (
                set(await agents.get_team_ids(agent_id))
                if agent.visibility == ResourceVisibility.teams
                else set()
            )
            for skill_id in sorted(wanted, key=str):
                skill = await self.repository.get_for_update(skill_id)
                if skill is None:
                    raise NotFoundError(self.not_found_message)
                if not audience_contains(
                    parent_visibility=agent.visibility,
                    parent_owner_id=agent.owner_id,
                    parent_team_ids=agent_team_ids,
                    child_visibility=skill.visibility,
                    child_owner_id=skill.owner_id,
                    child_team_ids=(
                        set(await self.repository.list_team_ids(skill_id))
                        if skill.visibility == ResourceVisibility.teams
                        else set()
                    ),
                ):
                    raise DomainValidationError(
                        f"Skill '{skill.name}' is more private than this agent"
                    )
                await self._ensure_skill_visible_to_grantees(
                    agents,
                    agent.id,
                    skill.owner_id,
                    skill.visibility,
                    (
                        set(await self.repository.list_team_ids(skill_id))
                        if skill.visibility == ResourceVisibility.teams
                        else set()
                    ),
                )
        current = await self.repository.list_attached_ids(agent_id)
        if wanted == current:
            return
        await self.repository.delete_links(agent_id, current - wanted)
        await self.repository.add_links(agent_id, wanted - current)


def _reject_files(data: SkillSave) -> None:
    """A skill written in the app is one SKILL.md and nothing else.

    Supporting files — references, assets, and the `scripts/` a skill needs
    code execution for — reach the library only through a repository, where
    they are reviewed and versioned. This guards the two in-app writes; the
    sync path builds its rows straight from `SkillCreateDB` and is untouched.
    """
    if data.files:
        raise DomainValidationError(
            "A skill written here is a single SKILL.md. Files and scripts come "
            "from a connected repository."
        )


def _name_taken(name: str) -> AlreadyExistsError:
    return AlreadyExistsError(
        f"A skill named '{name}' is already in the library. Skill names are "
        "unique across the workspace — agents address a skill by its name."
    )


def _can_edit(owner_id: UUID, user: UserDB) -> bool:
    return owner_id == user.id or user.role == WorkspaceRole.admin


def _is_sourced(source_revision: str | None) -> bool:
    """Whether the content came from a repository. `source_revision` is the
    pin — the commit it was read at — and only a sync or an adopt writes it.
    Not `digest`, which every save computes, in-app skills included."""
    return source_revision is not None


def _is_detached(source_revision: str | None, source_id: UUID | None) -> bool:
    """Pinned content whose repository is no longer connected: the pin
    without the live link. Two columns, no third state to migrate."""
    return _is_sourced(source_revision) and source_id is None


def _repository_owns(row: SkillDB) -> str:
    """Why a change was refused: a sourced skill is edited where its files
    come from, and a detached one has to be connected again first."""
    if _is_detached(row.source_revision, row.source_id):
        return (
            "This skill came from a repository that is no longer connected. "
            "Connect it again to change it — or delete it from the library."
        )
    return "This skill is synced from a repository — change it there, then sync"


def _columns(bundle: SkillBundle) -> dict:
    """The row columns a validated bundle fills."""
    return {
        "name": bundle.name,
        "description": bundle.description,
        "content": bundle.content,
        "files": [file.model_dump(mode="json") for file in bundle.files],
        "digest": bundle_digest(bundle.file_bytes()),
    }


def _update_available(digest: str | None, latest_digest: str | None) -> bool:
    return latest_digest is not None and digest is not None and latest_digest != digest


def _version_bundle(version: SkillVersionDB) -> SkillBundle:
    return parse_skill(
        version.content, [SkillFile.model_validate(f) for f in version.files]
    )


def get_skill_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> SkillService:
    return SkillService(db, workspace_id)
