from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import EffectivePermission
from app.database import get_db
from app.exceptions import (
    AlreadyExistsError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.service import BaseService
from app.skills.bundles import parse_skill, skill_markdown
from app.skills.models import AgentSkillDB, SkillDB
from app.skills.repository import SkillRepository
from app.skills.schemas import SkillBundle, SkillResponse, SkillSave
from app.users.models import UserDB, WorkspaceRole


class SkillService(BaseService[SkillDB, SkillRepository]):
    not_found_message = "Skill not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, SkillRepository(db))

    async def authorize(self, skill_id: UUID, user: UserDB, *, edit=False, lock=False):
        row = (
            await self.repository.lock(skill_id)
            if lock
            else await self.repository.get(skill_id)
        )
        if row is None:
            raise NotFoundError("Skill not found")
        if edit and row.owner_id != user.id and user.role != WorkspaceRole.admin:
            raise PermissionDeniedError(
                "Only the owner or a workspace admin can edit this skill"
            )
        return row

    async def response(self, row: SkillDB, user: UserDB) -> SkillResponse:
        bundle = SkillBundle.model_validate(row.bundle)
        return SkillResponse(
            id=row.id,
            owner_id=row.owner_id,
            revision=row.revision,
            name=bundle.name,
            description=bundle.description,
            instructions=bundle.instructions,
            content=skill_markdown(bundle),
            files=bundle.files,
            can_edit=row.owner_id == user.id or user.role == WorkspaceRole.admin,
        )

    async def list(self, user: UserDB):
        return [
            await self.response(row, user)
            for row in await self.repository.list_recent_first()
        ]

    async def save(self, data: SkillSave, user: UserDB, skill_id: UUID | None = None):
        try:
            bundle = parse_skill(data.content, data.files)
        except ValueError as exc:
            raise DomainValidationError(str(exc)) from exc
        if skill_id is None:
            row = await self.repository.add(
                SkillDB(owner_id=user.id, bundle=bundle.model_dump(mode="json"))
            )
        else:
            row = await self.authorize(skill_id, user, edit=True, lock=True)
            if data.revision != row.revision:
                raise AlreadyExistsError("This skill changed. Reload before saving.")
            if bundle.name != row.bundle["name"] and await self.repository.bindings(
                skill_id=row.id
            ):
                raise DomainValidationError("Detach the skill before changing its name")
            row.bundle = bundle.model_dump(mode="json")
            row.revision += 1
            await self.repository.add(row)
        return await self.response(row, user)

    async def delete(self, skill_id: UUID, user: UserDB):
        row = await self.authorize(skill_id, user, edit=True, lock=True)
        if await self.repository.bindings(skill_id=skill_id):
            raise DomainValidationError(
                "Detach this skill from its agents before deleting it"
            )
        await self.repository.delete(row)

    async def agent_gate(self, agent_id: UUID, user: UserDB, *, edit=True):
        await AgentService(self.db).require_permission(
            agent_id,
            at_least=EffectivePermission.editor if edit else EffectivePermission.member,
            action="configure skills" if edit else "use this agent",
            user_id=user.id,
            user_role=user.role,
            user_team_id=user.team_id,
        )

    async def attachments(self, agent_id: UUID, user: UserDB):
        await self.agent_gate(agent_id, user, edit=False)
        result = []
        for binding in await self.repository.bindings(agent_id=agent_id):
            row = await self.authorize(binding.skill_id, user)
            result.append({"skill_id": row.id, "name": row.bundle["name"]})
        return result

    async def attach(self, agent_id: UUID, skill_id: UUID, user: UserDB):
        await self.agent_gate(agent_id, user)
        row = await self.authorize(skill_id, user, lock=True)
        for binding in await self.repository.bindings(agent_id=agent_id):
            if binding.skill_id == skill_id:
                return
            other = await self.repository.get(binding.skill_id)
            if other is not None and other.bundle["name"] == row.bundle["name"]:
                raise DomainValidationError("An attached skill already uses this name")
        await self.repository.add(AgentSkillDB(agent_id=agent_id, skill_id=skill_id))

    async def detach(self, agent_id: UUID, skill_id: UUID, user: UserDB):
        await self.agent_gate(agent_id, user)
        for row in await self.repository.bindings(agent_id=agent_id):
            if row.skill_id == skill_id:
                await self.db.delete(row)
        await self.db.flush()


async def get_skill_service(db: AsyncSession = Depends(get_db)) -> SkillService:
    return SkillService(db)
