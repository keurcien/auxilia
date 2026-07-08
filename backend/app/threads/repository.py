from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB
from app.agents.runs.state import RunStatus
from app.pagination import PageParams
from app.repository import BaseRepository
from app.threads.models import FIRST_PARTY_SOURCES, ThreadDB
from app.users.models import UserDB


class ThreadRepository(BaseRepository[ThreadDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(ThreadDB, db)

    async def get(self, id: str) -> ThreadDB | None:
        stmt = select(ThreadDB).where(ThreadDB.id == id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_ids_for_agent(self, agent_id: UUID) -> list[str]:
        stmt = select(ThreadDB.id).where(ThreadDB.agent_id == agent_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_for_agent(self, agent_id: UUID) -> None:
        stmt = delete(ThreadDB).where(ThreadDB.agent_id == agent_id)
        await self.db.execute(stmt)

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

    async def list_for_user(self, user_id: UUID, page: PageParams):
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
            .where(ThreadDB.source.in_(FIRST_PARTY_SOURCES))
            .order_by(ThreadDB.created_at.desc(), ThreadDB.id)
        )
        result, total = await self.paginate(stmt, page)
        return result.all(), total

    async def list_for_trigger(
        self, trigger_id: UUID, since: datetime | None = None
    ) -> list[ThreadDB]:
        stmt = (
            select(ThreadDB)
            .where(ThreadDB.trigger_id == trigger_id)
            .order_by(ThreadDB.created_at.desc())
        )
        if since is not None:
            stmt = stmt.where(ThreadDB.created_at >= since)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def set_last_run_status(self, thread_id: str, status: RunStatus) -> None:
        """Stamp the outcome of the thread's most recent run (single UPDATE;
        a deleted thread is a harmless 0-row no-op)."""
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(last_run_status=status)
        )
        await self.db.execute(stmt)

    async def list_for_agent(self, agent_id: UUID, page: PageParams):
        stmt = (
            select(
                ThreadDB,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
                AgentDB.is_archived,
                UserDB.email,
                UserDB.name,
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .join(UserDB, ThreadDB.user_id == UserDB.id)
            .where(ThreadDB.agent_id == agent_id)
            .order_by(ThreadDB.created_at.desc(), ThreadDB.id)
        )
        result, total = await self.paginate(stmt, page)
        return result.all(), total
