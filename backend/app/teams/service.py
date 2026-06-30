from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import AlreadyExistsError
from app.service import BaseService
from app.teams.models import TeamDB
from app.teams.repository import TeamRepository
from app.teams.schemas import TeamCreate, TeamPatch


class TeamService(BaseService[TeamDB, TeamRepository]):
    not_found_message = "Team not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, TeamRepository(db))

    async def _ensure_name_available(self, name: str) -> None:
        if await self.repository.get_by_name(name):
            raise AlreadyExistsError("Team name already exists")

    async def list(self) -> list[TeamDB]:
        return await self.repository.list_all()

    async def get(self, team_id: UUID) -> TeamDB:
        return await self.get_or_404(team_id)

    async def create(self, data: TeamCreate) -> TeamDB:
        await self._ensure_name_available(data.name)
        return await self.repository.create(data)

    async def update(self, team_id: UUID, data: TeamPatch) -> TeamDB:
        team = await self.get_or_404(team_id)
        update_data = data.model_dump(exclude_unset=True)
        new_name = update_data.get("name")
        if "name" in update_data and new_name is not None and new_name != team.name:
            await self._ensure_name_available(new_name)
        return await self.repository.update(team, data)

    async def delete(self, team_id: UUID) -> None:
        team = await self.get_or_404(team_id)
        await self.repository.delete(team)


def get_team_service(db: AsyncSession = Depends(get_db)) -> TeamService:
    return TeamService(db)
