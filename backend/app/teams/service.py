from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import AlreadyExistsError, DomainValidationError, NotFoundError
from app.service import BaseService
from app.teams.models import TeamDB
from app.teams.repository import TeamRepository
from app.teams.schemas import TeamCreate, TeamCreateDB, TeamPatch, TeamResponse


class TeamService(BaseService[TeamDB, TeamRepository]):
    not_found_message = "Team not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, TeamRepository(db))

    async def _ensure_name_available(self, workspace_id: UUID, name: str) -> None:
        if await self.repository.get_by_name(workspace_id, name):
            raise AlreadyExistsError("Team name already exists")

    async def list(self, workspace_id: UUID) -> list[TeamResponse]:
        rows = await self.repository.list_with_member_counts(workspace_id)
        return [
            TeamResponse.model_validate(team, update={"member_count": count})
            for team, count in rows
        ]

    async def get(self, team_id: UUID, workspace_id: UUID) -> TeamDB:
        team = await self.repository.get_in_workspace(team_id, workspace_id)
        if team is None:
            raise NotFoundError(self.not_found_message)
        return team

    async def create(self, data: TeamCreate, workspace_id: UUID) -> TeamDB:
        if not data.name or not data.name.strip():
            raise DomainValidationError("Team name cannot be empty")
        await self._ensure_name_available(workspace_id, data.name)
        try:
            return await self.repository.create(
                TeamCreateDB(
                    workspace_id=workspace_id,
                    name=data.name,
                    color=data.color,
                )
            )
        except IntegrityError as exc:
            # Lost a race against a concurrent create with the same name.
            raise AlreadyExistsError("Team name already exists") from exc

    async def update(
        self, team_id: UUID, workspace_id: UUID, data: TeamPatch
    ) -> TeamDB:
        team = await self.get(team_id, workspace_id)
        update_data = data.model_dump(exclude_unset=True)
        if "name" in update_data:
            new_name = update_data["name"]
            if not new_name or not new_name.strip():
                raise DomainValidationError("Team name cannot be empty")
            if new_name != team.name:
                await self._ensure_name_available(workspace_id, new_name)
        try:
            return await self.repository.update(team, data)
        except IntegrityError as exc:
            raise AlreadyExistsError("Team name already exists") from exc

    async def delete(self, team_id: UUID, workspace_id: UUID) -> None:
        team = await self.repository.get_in_workspace_for_update(team_id, workspace_id)
        if team is None:
            raise NotFoundError(self.not_found_message)
        in_use = await self.repository.is_used_for_resource_visibility(team_id)
        if in_use is True:
            raise DomainValidationError(
                "Team cannot be deleted while it is used by resource visibility"
            )
        await self.repository.delete(team)


def get_team_service(db: AsyncSession = Depends(get_db)) -> TeamService:
    return TeamService(db)
