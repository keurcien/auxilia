from uuid import UUID

from sqlalchemy import exists, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentTeamDB
from app.mcp.servers.models import MCPServerTeamDB
from app.repository import BaseRepository
from app.skills.models import SkillTeamDB
from app.teams.models import TeamDB
from app.triggers.models import TriggerTeamDB
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

    async def get_in_workspace_for_update(
        self, team_id: UUID, workspace_id: UUID
    ) -> TeamDB | None:
        stmt = (
            select(TeamDB)
            .where(
                TeamDB.id == team_id,
                TeamDB.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_in_workspace_for_key_share(
        self, team_id: UUID, workspace_id: UUID
    ) -> TeamDB | None:
        stmt = (
            select(TeamDB)
            .where(
                TeamDB.id == team_id,
                TeamDB.workspace_id == workspace_id,
            )
            .with_for_update(read=True, key_share=True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def is_used_for_resource_visibility(self, team_id: UUID) -> bool:
        stmt = select(
            or_(
                exists().where(AgentTeamDB.team_id == team_id),
                exists().where(MCPServerTeamDB.team_id == team_id),
                exists().where(SkillTeamDB.team_id == team_id),
                exists().where(TriggerTeamDB.team_id == team_id),
            )
        )
        return bool((await self.db.execute(stmt)).scalar_one())
