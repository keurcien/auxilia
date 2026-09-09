from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.agents.runs.models import RunDB
from app.agents.runs.state import RunStatus
from app.repository import BaseRepository
from app.skills.models import AgentSkillDB, SkillDB


class SkillRepository(BaseRepository[SkillDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillDB, db)

    async def list_recent_first(self):
        stmt = select(SkillDB).order_by(col(SkillDB.updated_at).desc())
        return (await self.db.execute(stmt)).scalars().all()

    async def bindings_for_agents(self, agent_ids):
        stmt = select(AgentSkillDB).where(
            col(AgentSkillDB.agent_id).in_(list(agent_ids))
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def get_many(self, skill_ids):
        stmt = select(SkillDB).where(col(SkillDB.id).in_(list(skill_ids)))
        return (await self.db.execute(stmt)).scalars().all()

    async def lock(self, skill_id: UUID):
        stmt = (
            select(SkillDB)
            .where(SkillDB.id == skill_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def bindings(
        self, *, skill_id: UUID | None = None, agent_id: UUID | None = None
    ):
        stmt = select(AgentSkillDB)
        if skill_id is not None:
            stmt = stmt.where(AgentSkillDB.skill_id == skill_id)
        if agent_id is not None:
            stmt = stmt.where(AgentSkillDB.agent_id == agent_id)
        return (await self.db.execute(stmt)).scalars().all()

    async def interrupted_snapshot(self, record):
        stmt = (
            select(RunDB)
            .where(
                RunDB.thread_id == record.thread_id,
                RunDB.id != record.id,
                RunDB.status == RunStatus.interrupted,
            )
            .order_by(col(RunDB.created_at).desc())
            .limit(1)
        )
        previous = (await self.db.execute(stmt)).scalar_one_or_none()
        return previous.skill_snapshot if previous is not None else None

    async def freeze_snapshot(self, record, snapshot):
        persisted = await self.db.get(RunDB, record.id)
        if persisted is None:
            raise ValueError("Run not found")
        persisted.skill_snapshot = snapshot
        await self.db.commit()

    async def add(self, row):
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row
