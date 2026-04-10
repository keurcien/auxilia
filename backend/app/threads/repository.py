from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB
from app.repositories import BaseRepository
from app.threads.models import ThreadDB


class ThreadRepository(BaseRepository[ThreadDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(ThreadDB, db)

    async def get(self, id: str) -> ThreadDB | None:
        stmt = select(ThreadDB).where(ThreadDB.id == id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_agent(self, thread_id: str):
        stmt = (
            select(
                ThreadDB,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
                AgentDB.is_archived,
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .where(ThreadDB.id == thread_id)
        )
        result = await self.db.execute(stmt)
        return result.one_or_none()

    async def list_for_user(self, user_id: UUID):
        stmt = (
            select(
                ThreadDB,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
                AgentDB.is_archived,
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .where(ThreadDB.user_id == user_id)
            .order_by(ThreadDB.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.all()
