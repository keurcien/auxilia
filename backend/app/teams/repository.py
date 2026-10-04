from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.repository import BaseRepository
from app.teams.models import TeamDB
from app.workspaces.models import WorkspaceMembershipDB


class TeamRepository(BaseRepository[TeamDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(TeamDB, db)

    async def list_with_member_counts(
        self, workspace_id: UUID
    ) -> list[tuple[TeamDB, int]]:
        stmt = (
            select(TeamDB, func.count(WorkspaceMembershipDB.id))
            .outerjoin(
                WorkspaceMembershipDB,
                WorkspaceMembershipDB.team_id == TeamDB.id,
            )
            .where(TeamDB.workspace_id == workspace_id)
            .group_by(TeamDB.id)
            .order_by(TeamDB.name.asc())
        )
        result = await self.db.execute(stmt)
        return [(team, count) for team, count in result.all()]

    async def get_by_name(self, workspace_id: UUID, name: str) -> TeamDB | None:
        stmt = select(TeamDB).where(
            TeamDB.workspace_id == workspace_id,
            TeamDB.name == name,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_in_workspace(
        self, team_id: UUID, workspace_id: UUID
    ) -> TeamDB | None:
        stmt = select(TeamDB).where(
            TeamDB.id == team_id,
            TeamDB.workspace_id == workspace_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
