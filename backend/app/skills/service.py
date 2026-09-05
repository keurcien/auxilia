from __future__ import annotations

import builtins
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
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
from app.skills.models import AgentSkillDB, SkillDB, SkillTestDB, SkillVersionDB
from app.skills.repository import SkillRepository
from app.skills.schemas import (
    SkillBundle,
    SkillResponse,
    SkillSave,
    SkillTest,
    SkillVersionResponse,
)
from app.threads.models import ThreadSource
from app.threads.schemas import ThreadCreate
from app.threads.service import ThreadService
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
        if row is None or (
            row.owner_id != user.id
            and row.visibility != "workspace"
            and user.role != WorkspaceRole.admin
        ):
            raise NotFoundError("Skill not found")
        if edit and row.owner_id != user.id and user.role != WorkspaceRole.admin:
            raise PermissionDeniedError(
                "Only the owner or a workspace admin can edit this skill"
            )
        return row

    async def response(self, row: SkillDB, user: UserDB) -> SkillResponse:
        return SkillResponse(
            id=row.id,
            owner_id=row.owner_id,
            visibility=row.visibility,
            revision=row.revision,
            draft=SkillBundle.model_validate(row.draft),
            can_edit=row.owner_id == user.id or user.role == WorkspaceRole.admin,
            versions=[
                SkillVersionResponse(
                    id=v.id,
                    number=v.number,
                    bundle=SkillBundle.model_validate(v.bundle),
                    created_at=v.created_at,
                )
                for v in await self.repository.versions(row.id)
            ],
            used_by=[
                b.agent_id for b in await self.repository.bindings(skill_id=row.id)
            ]
            if row.owner_id == user.id or user.role == WorkspaceRole.admin
            else [],
        )

    async def list(self, user: UserDB):
        return [
            await self.response(row, user)
            for row in await self.repository.visible(
                user.id, user.role == WorkspaceRole.admin
            )
        ]

    async def save(self, data: SkillSave, user: UserDB, skill_id: UUID | None = None):
        if skill_id is None:
            row = await self.repository.add(
                SkillDB(
                    owner_id=user.id,
                    visibility=data.visibility,
                    draft=data.bundle.model_dump(mode="json"),
                )
            )
        else:
            row = await self.authorize(skill_id, user, edit=True, lock=True)
            if data.revision != row.revision:
                raise AlreadyExistsError("This draft changed. Reload before saving.")
            # Names are stable after first publication: paths and attachments use them.
            if data.bundle.name != row.draft["name"] and await self.repository.versions(
                row.id
            ):
                raise DomainValidationError(
                    "A published skill's identifier cannot change"
                )
            row.draft = data.bundle.model_dump(mode="json")
            row.visibility = data.visibility
            row.revision += 1
            await self.repository.add(row)
        return await self.response(row, user)

    async def publish(self, skill_id: UUID, revision: int, user: UserDB):
        row = await self.authorize(skill_id, user, edit=True, lock=True)
        if revision != row.revision:
            raise AlreadyExistsError("This draft changed. Reload before publishing.")
        versions = await self.repository.versions(skill_id)
        await self.repository.add(
            SkillVersionDB(
                skill_id=skill_id,
                number=(versions[0].number + 1 if versions else 1),
                bundle=row.draft,
            )
        )
        row.revision += 1
        await self.repository.add(row)
        return await self.response(row, user)

    async def restore(
        self, skill_id: UUID, version_id: UUID, revision: int, user: UserDB
    ):
        row = await self.authorize(skill_id, user, edit=True)
        version = await self.repository.version(version_id)
        if version is None or version.skill_id != skill_id:
            raise NotFoundError("Version not found")
        return await self.save(
            SkillSave(
                bundle=SkillBundle.model_validate(version.bundle),
                revision=revision,
                visibility=row.visibility,
            ),
            user,
            skill_id,
        )

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

    async def compatibility(
        self, agent_id: UUID, bundle: SkillBundle
    ) -> builtins.list[str]:
        spec = await AgentRepository(self.db).get_run_spec(agent_id)
        if spec is None:
            raise NotFoundError("Agent not found")
        return self.missing(spec.agent, bundle)

    @staticmethod
    def missing(spec, bundle: SkillBundle) -> builtins.list[str]:
        missing = []
        if bundle.requires_code and spec.sandbox is None:
            missing.append("Code execution")
        connected = {b.mcp_server_id for b in spec.mcp_servers}
        missing.extend(
            f"MCP connection {sid}"
            for sid in bundle.required_mcp_server_ids
            if sid not in connected
        )
        return missing

    async def attachments(self, agent_id: UUID, user: UserDB):
        await self.agent_gate(agent_id, user, edit=False)
        result = []
        for binding in await self.repository.bindings(agent_id=agent_id):
            row = await self.authorize(binding.skill_id, user)
            version = await self.repository.version(binding.version_id)
            bundle = SkillBundle.model_validate(version.bundle)
            result.append(
                {
                    "skill_id": row.id,
                    "version_id": version.id,
                    "number": version.number,
                    "title": bundle.title,
                    "missing": await self.compatibility(agent_id, bundle),
                }
            )
        return result

    async def attach(
        self, agent_id: UUID, skill_id: UUID, version_id: UUID, user: UserDB
    ):
        await self.agent_gate(agent_id, user)
        await self.authorize(skill_id, user, lock=True)
        version = await self.repository.version(version_id)
        if version is None or version.skill_id != skill_id:
            raise NotFoundError("Published version not found")
        bundle = SkillBundle.model_validate(version.bundle)
        missing = await self.compatibility(agent_id, bundle)
        if missing:
            raise DomainValidationError("Needs: " + ", ".join(missing))
        bindings = await self.repository.bindings(agent_id=agent_id)
        current = None
        for b in bindings:
            if b.skill_id == skill_id:
                current = b
            else:
                other = await self.repository.version(b.version_id)
                if other.bundle["name"] == bundle.name:
                    raise DomainValidationError(
                        "An attached skill already uses this identifier"
                    )
        if current:
            current.version_id = version_id
        else:
            current = AgentSkillDB(
                agent_id=agent_id, skill_id=skill_id, version_id=version_id
            )
        await self.repository.add(current)

    async def detach(self, agent_id: UUID, skill_id: UUID, user: UserDB):
        await self.agent_gate(agent_id, user)
        for row in await self.repository.bindings(agent_id=agent_id):
            if row.skill_id == skill_id:
                await self.db.delete(row)
        await self.db.flush()

    async def test(self, skill_id: UUID, data: SkillTest, user: UserDB):
        row = await self.authorize(skill_id, user)
        await self.agent_gate(data.agent_id, user, edit=False)
        bundle = row.draft
        if data.version_id:
            version = await self.repository.version(data.version_id)
            if version is None or version.skill_id != skill_id:
                raise NotFoundError("Version not found")
            bundle = version.bundle
        missing = await self.compatibility(
            data.agent_id, SkillBundle.model_validate(bundle)
        )
        if missing:
            raise DomainValidationError("Needs: " + ", ".join(missing))
        thread = await ThreadService(self.db).create(
            ThreadCreate(
                agent_id=data.agent_id,
                model_id=data.model_id,
                first_message_content=data.prompt,
            ),
            user_id=user.id,
            source=ThreadSource.web,
        )
        test = await self.repository.add(
            SkillTestDB(skill_id=skill_id, thread_id=thread.id, bundle=bundle)
        )
        return {
            "test_id": test.id,
            "thread": thread,
            "prompt": f"Use the skill {bundle['name']} for this example.\n\n{data.prompt}",
        }

    async def test_history(self, skill_id, user):
        await self.authorize(skill_id, user, edit=True)
        return [
            {
                "id": row.id,
                "thread_id": row.thread_id,
                "result": row.result,
                "notes": row.notes,
                "created_at": row.created_at,
            }
            for row in await self.repository.tests(skill_id)
        ]

    async def feedback(self, skill_id, thread_id, data, user):
        await self.authorize(skill_id, user, edit=True)
        test = await self.repository.test_for_thread(thread_id)
        if test is None or test.skill_id != skill_id:
            raise NotFoundError("Test not found")
        test.result, test.notes = data.result, data.notes
        await self.repository.add(test)


async def get_skill_service(db: AsyncSession = Depends(get_db)) -> SkillService:
    return SkillService(db)
