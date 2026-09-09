from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.subagents.repository import SubagentRepository
from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    StaleRevisionError,
)
from app.service import BaseService
from app.skills.bundles import export_archive, parse_skill
from app.skills.models import SkillDB
from app.skills.repository import SkillRepository
from app.skills.schemas import (
    AgentSkillResponse,
    SkillBundle,
    SkillCreateDB,
    SkillResponse,
    SkillSave,
    SkillSummary,
)
from app.users.models import UserDB, WorkspaceRole


class SkillService(BaseService[SkillDB, SkillRepository]):
    """The skill library, and which agents each skill is enabled on.

    Every workspace user can read and use every skill; only its owner or a
    workspace admin can change or delete it. Enabling a skill on an agent is
    part of the agent's config save, so the *agent* permission gate
    (`AgentService.set_config`) is what protects `set_for_agent`.
    """

    not_found_message = "Skill not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, SkillRepository(db))
        self._links = SubagentRepository(db)

    # -- the library ---------------------------------------------------------

    async def list_summaries(self, user: UserDB) -> list[SkillSummary]:
        return [
            SkillSummary(**row._mapping, can_edit=_can_edit(row.owner_id, user))
            for row in await self.repository.list_summaries()
        ]

    async def get(self, skill_id: UUID, user: UserDB) -> SkillResponse:
        return self._response(await self.get_or_404(skill_id), user)

    async def create(self, data: SkillSave, user: UserDB) -> SkillResponse:
        bundle = parse_skill(data.content, data.files)
        row = await self.repository.create(
            SkillCreateDB(owner_id=user.id, **_columns(bundle))
        )
        return self._response(row, user)

    async def update(
        self, skill_id: UUID, data: SkillSave, user: UserDB
    ) -> SkillResponse:
        bundle = parse_skill(data.content, data.files)
        row = await self._editable(skill_id, user)
        if data.revision != row.revision:
            raise StaleRevisionError(
                "This skill changed since you opened it. Reload it before saving."
            )
        if bundle.name != row.name and await self.repository.is_attached(row.id):
            # Agents address a skill by name and share one namespace per graph;
            # renaming in place could collide with, or hide, a live catalog.
            raise DomainValidationError(
                "Disable this skill on every agent before renaming it"
            )
        row.sqlmodel_update({**_columns(bundle), "revision": row.revision + 1})
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return self._response(row, user)

    async def delete(self, skill_id: UUID, user: UserDB) -> None:
        row = await self._editable(skill_id, user)
        if await self.repository.is_attached(row.id):
            raise DomainValidationError(
                "Disable this skill on every agent before deleting it"
            )
        await self.repository.delete(row)

    async def export(self, skill_id: UUID) -> tuple[str, bytes]:
        """`(name, zip bytes)` for the download endpoint."""
        row = await self.get_or_404(skill_id)
        return row.name, export_archive(row.to_bundle())

    async def _editable(self, skill_id: UUID, user: UserDB) -> SkillDB:
        row = await self.repository.get_for_update(skill_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        if not _can_edit(row.owner_id, user):
            raise PermissionDeniedError(
                "Only the skill's owner or a workspace admin can change it"
            )
        return row

    @staticmethod
    def _response(row: SkillDB, user: UserDB) -> SkillResponse:
        bundle = row.to_bundle()
        return SkillResponse(
            id=row.id,
            owner_id=row.owner_id,
            name=bundle.name,
            description=bundle.description,
            revision=row.revision,
            file_count=len(bundle.files),
            updated_at=row.updated_at,
            can_edit=_can_edit(row.owner_id, user),
            content=bundle.content,
            files=bundle.files,
        )

    # -- agent bindings ------------------------------------------------------

    async def list_for_agent(self, agent_id: UUID) -> list[AgentSkillResponse]:
        return [
            AgentSkillResponse(**row._mapping)
            for row in await self.repository.list_attached(agent_id)
        ]

    async def set_for_agent(self, agent_id: UUID, skill_ids: Iterable[UUID]) -> None:
        """Whole-set replace of an agent's skills, from the config save."""
        wanted = set(skill_ids)
        if wanted - await self.repository.list_existing_ids(wanted):
            raise NotFoundError(self.not_found_message)
        current = await self.repository.list_attached_ids(agent_id)
        if wanted == current:
            return
        # The agent's graph — a supervisor and its subagents — runs with one
        # skill set, so the names must stay unique across it, not just here.
        for graph in await self._graphs_of(agent_id):
            await self.ensure_unique_names(graph - {agent_id}, adding=wanted)
        await self.repository.delete_links(agent_id, current - wanted)
        await self.repository.add_links(agent_id, wanted - current)

    async def ensure_unique_names(
        self, agent_ids: Iterable[UUID], *, adding: Iterable[UUID] = ()
    ) -> None:
        """Refuse a graph whose members hold two *different* skills of one
        name (the same skill on several members is one catalog entry).

        Called with a graph's members when a skill set changes
        (`set_for_agent`) and when a subagent joins a supervisor
        (`SubagentService`), since that merges two sets. `adding` are skill
        ids about to join the set, on top of what the agents already hold.
        """
        by_name: dict[str, UUID] = {}
        pairs = [
            *await self.repository.list_names_for_agents(agent_ids),
            *await self.repository.list_names(adding),
        ]
        for skill_id, name in pairs:
            if by_name.setdefault(name, skill_id) != skill_id:
                raise DomainValidationError(
                    f"Two different skills named '{name}' would be enabled on "
                    "this agent's graph (a supervisor and its subagents share "
                    "one skill set). Rename one of them first."
                )

    async def _graphs_of(self, agent_id: UUID) -> list[set[UUID]]:
        """Every graph the agent runs in: each supervisor's (supervisor plus
        all its subagents) when it is a subagent, else its own. One level,
        like the run itself."""
        roots = await self._links.list_supervisor_ids(agent_id) or [agent_id]
        graphs = []
        for root in roots:
            links = await self._links.list_for_supervisor(root)
            graphs.append({root, *(link.subagent_id for link in links)})
        return graphs


def _can_edit(owner_id: UUID, user: UserDB) -> bool:
    return owner_id == user.id or user.role == WorkspaceRole.admin


def _columns(bundle: SkillBundle) -> dict:
    """The row columns a validated bundle fills."""
    return {
        "name": bundle.name,
        "description": bundle.description,
        "content": bundle.content,
        "files": [file.model_dump(mode="json") for file in bundle.files],
    }


def get_skill_service(db: AsyncSession = Depends(get_db)) -> SkillService:
    return SkillService(db)
