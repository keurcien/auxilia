from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB
from app.pagination import PageParams
from app.repository import BaseRepository
from app.runtime.runs.state import RunStatus
from app.threads.models import FIRST_PARTY_SOURCES, ThreadDB
from app.users.models import UserDB


class ThreadRepository(BaseRepository[ThreadDB]):
    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(ThreadDB, db)
        self.workspace_id = workspace_id

    def _scope(self, stmt):
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        return stmt

    async def get(self, id: str) -> ThreadDB | None:
        stmt = self._scope(select(ThreadDB).where(ThreadDB.id == id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_ids_for_agent(self, agent_id: UUID) -> list[str]:
        stmt = self._scope(select(ThreadDB.id).where(ThreadDB.agent_id == agent_id))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_ids(self) -> list[str]:
        stmt = self._scope(select(ThreadDB.id))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_for_agent(self, agent_id: UUID) -> None:
        stmt = self._scope(delete(ThreadDB).where(ThreadDB.agent_id == agent_id))
        await self.db.execute(stmt)

    async def get_with_agent(self, thread_id: str):
        stmt = (
            select(
                ThreadDB,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
                AgentDB.image_revision,
                AgentDB.is_archived,
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .where(ThreadDB.id == thread_id)
        )
        stmt = self._scope(stmt)
        result = await self.db.execute(stmt)
        return result.one_or_none()

    async def list_for_user(
        self, user_id: UUID, page: PageParams, query: str | None = None
    ):
        stmt = (
            select(
                ThreadDB,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
                AgentDB.image_revision,
                AgentDB.is_archived,
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .where(ThreadDB.user_id == user_id)
            .where(ThreadDB.source.in_(FIRST_PARTY_SOURCES))
            .order_by(ThreadDB.created_at.desc(), ThreadDB.id)
        )
        if query and (term := query.strip()):
            escape = "\\"
            escaped_term = (
                term.replace(escape, escape * 2)
                .replace("%", f"{escape}%")
                .replace("_", f"{escape}_")
            )
            pattern = f"%{escaped_term}%"
            stmt = stmt.where(
                or_(
                    ThreadDB.first_message_content.ilike(pattern, escape=escape),
                    AgentDB.name.ilike(pattern, escape=escape),
                )
            )
        stmt = self._scope(stmt)
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
        stmt = self._scope(stmt)
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
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def set_awaiting_input(self, thread_id: str, awaiting: bool) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(awaiting_input=awaiting)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def set_queue_edit_lease(
        self, thread_id: str, run_id: str, expires_at: datetime
    ) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(
                queue_edit_run_id=run_id,
                queue_edit_expires_at=expires_at,
            )
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def clear_queue_edit_lease(self, thread_id: str, run_id: str) -> None:
        stmt = (
            update(ThreadDB)
            .where(
                ThreadDB.id == thread_id,
                ThreadDB.queue_edit_run_id == run_id,
            )
            .values(queue_edit_run_id=None, queue_edit_expires_at=None)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def clear_sandbox(self, source_id: UUID) -> None:
        """Forget the sandbox of every thread stamped by this sandbox row.

        Called when the row is deleted: the id it issued is worthless, and
        leaving it behind would let a later binding try to reconnect to it.
        """
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.sandbox_source_id == source_id)
            .values(sandbox_id=None, sandbox_source_id=None)
        )
        await self.db.execute(stmt)

    async def set_sandbox_id(
        self, thread_id: str, sandbox_id: str, source_id: UUID | None = None
    ) -> None:
        """Record the sandbox the thread's runs reconnect to, and which
        sandbox row issued it (single UPDATE)."""
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(sandbox_id=sandbox_id, sandbox_source_id=source_id)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def list_for_agent(self, agent_id: UUID, page: PageParams):
        stmt = (
            select(
                ThreadDB,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
                AgentDB.image_revision,
                AgentDB.is_archived,
                UserDB.email,
                UserDB.name,
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .join(UserDB, ThreadDB.user_id == UserDB.id)
            .where(ThreadDB.agent_id == agent_id)
            .order_by(ThreadDB.created_at.desc(), ThreadDB.id)
        )
        stmt = self._scope(stmt)
        result, total = await self.paginate(stmt, page)
        return result.all(), total
