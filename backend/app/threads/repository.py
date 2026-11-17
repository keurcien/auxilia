from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB
from app.pagination import PageParams
from app.repository import BaseRepository
from app.runtime.runs.state import RunStatus
from app.threads.models import (
    FIRST_PARTY_SOURCES,
    ThreadDB,
    ThreadReadStateDB,
    ThreadSource,
    ThreadToolMode,
)
from app.users.models import UserDB


class ThreadRepository(BaseRepository[ThreadDB]):
    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(ThreadDB, db)
        self.workspace_id = workspace_id

    def _scope(self, stmt):
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        return stmt

    @staticmethod
    def _is_unread():
        # Completed threads are read-only, so they can never be marked read.
        return and_(
            ThreadDB.completed_at.is_(None),
            or_(
                ThreadDB.response_version
                > func.coalesce(ThreadReadStateDB.last_read_version, 0),
                func.coalesce(ThreadReadStateDB.manually_unread, False).is_(True),
            ),
        )

    @staticmethod
    def _join_read_state(stmt, viewer_id: UUID):
        return stmt.outerjoin(
            ThreadReadStateDB,
            and_(
                ThreadReadStateDB.thread_id == ThreadDB.id,
                ThreadReadStateDB.user_id == viewer_id,
            ),
        )

    async def get(self, id: str) -> ThreadDB | None:
        stmt = self._scope(select(ThreadDB).where(ThreadDB.id == id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def lock(self, thread_id: str) -> ThreadDB | None:
        """Serialize operations that allocate names within one thread."""
        stmt = self._scope(
            select(ThreadDB).where(ThreadDB.id == thread_id).with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def lock_owned(self, thread_id: str, user_id: UUID) -> ThreadDB | None:
        stmt = self._scope(
            select(ThreadDB)
            .where(ThreadDB.id == thread_id, ThreadDB.user_id == user_id)
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def lock_owned_many(
        self, thread_ids: list[str], user_id: UUID
    ) -> list[ThreadDB]:
        stmt = self._scope(
            select(ThreadDB)
            .where(
                ThreadDB.id.in_(thread_ids),
                ThreadDB.user_id == user_id,
            )
            .order_by(ThreadDB.id)
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

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

    async def get_with_agent(self, thread_id: str, viewer_id: UUID):
        stmt = (
            select(
                ThreadDB,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
                AgentDB.image_revision,
                AgentDB.is_archived,
                self._is_unread().label("is_unread"),
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .where(ThreadDB.id == thread_id)
        )
        stmt = self._join_read_state(stmt, viewer_id)
        stmt = self._scope(stmt)
        result = await self.db.execute(stmt)
        return result.one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        page: PageParams,
        query: str | None = None,
        *,
        project_id: UUID | None = None,
        folder_id: UUID | None = None,
        placement: Literal["all", "assigned", "unassigned"] = "all",
        include_api: bool = False,
        read_status: Literal["all", "read", "unread"] = "all",
        completion: Literal["all", "completed", "uncompleted"] = "all",
        source: ThreadSource | None = None,
        created_from: datetime | None = None,
        created_before: datetime | None = None,
        order: Literal["created", "activity"] = "created",
    ):
        sources = (
            (*FIRST_PARTY_SOURCES, ThreadSource.api)
            if include_api
            else FIRST_PARTY_SOURCES
        )
        stmt = (
            select(
                ThreadDB,
                AgentDB.name,
                AgentDB.emoji,
                AgentDB.color,
                AgentDB.image_revision,
                AgentDB.is_archived,
                self._is_unread().label("is_unread"),
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .where(ThreadDB.user_id == user_id)
            .where(ThreadDB.source.in_(sources))
        )
        stmt = stmt.order_by(
            *(
                (
                    ThreadDB.updated_at.desc(),
                    ThreadDB.created_at.desc(),
                    ThreadDB.id,
                )
                if order == "activity"
                else (ThreadDB.created_at.desc(), ThreadDB.id)
            )
        )
        stmt = self._join_read_state(stmt, user_id)
        if project_id is not None:
            stmt = stmt.where(ThreadDB.project_id == project_id)
        if folder_id is not None:
            stmt = stmt.where(ThreadDB.folder_id == folder_id)
        if placement == "assigned":
            stmt = stmt.where(ThreadDB.project_id.is_not(None))
        elif placement == "unassigned":
            stmt = stmt.where(ThreadDB.project_id.is_(None))
        if read_status == "read":
            stmt = stmt.where(~self._is_unread())
        elif read_status == "unread":
            stmt = stmt.where(self._is_unread())
        if completion == "completed":
            stmt = stmt.where(ThreadDB.completed_at.is_not(None))
        elif completion == "uncompleted":
            stmt = stmt.where(ThreadDB.completed_at.is_(None))
        if source is not None:
            stmt = stmt.where(ThreadDB.source == source)
        if created_from is not None:
            stmt = stmt.where(ThreadDB.created_at >= created_from)
        if created_before is not None:
            stmt = stmt.where(ThreadDB.created_at < created_before)
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

    async def increment_response_version(self, thread_id: str) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(response_version=ThreadDB.response_version + 1)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def set_read_state(
        self,
        thread: ThreadDB,
        user_id: UUID,
        *,
        unread: bool,
    ) -> None:
        stmt = (
            pg_insert(ThreadReadStateDB)
            .values(
                thread_id=thread.id,
                user_id=user_id,
                last_read_version=thread.response_version,
                manually_unread=unread,
            )
            .on_conflict_do_update(
                index_elements=[
                    ThreadReadStateDB.thread_id,
                    ThreadReadStateDB.user_id,
                ],
                set_={
                    "last_read_version": thread.response_version,
                    "manually_unread": unread,
                    "updated_at": func.now(),
                },
            )
        )
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

    async def set_resources(
        self,
        thread_id: str,
        disabled_mcp_server_ids: list[str],
        disabled_skill_ids: list[str],
        disabled_sandbox_ids: list[str],
        disabled_subagent_ids: list[str],
        tool_mode: ThreadToolMode | None,
    ) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(
                disabled_mcp_server_ids=disabled_mcp_server_ids,
                disabled_skill_ids=disabled_skill_ids,
                disabled_sandbox_ids=disabled_sandbox_ids,
                disabled_subagent_ids=disabled_subagent_ids,
                tool_mode=tool_mode,
            )
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def set_model(
        self, thread_id: str, model_id: str, reasoning_effort: str | None
    ) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(model_id=model_id, reasoning_effort=reasoning_effort)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def set_notifications_enabled(self, thread_id: str, enabled: bool) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(notifications_enabled=enabled)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def set_memories_enabled(self, thread_id: str, enabled: bool) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(memories_enabled=enabled)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def set_placement(
        self,
        thread_id: str,
        project_id: UUID | None,
        folder_id: UUID | None,
    ) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(project_id=project_id, folder_id=folder_id)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def set_placement_many(
        self,
        thread_ids: list[str],
        user_id: UUID,
        project_id: UUID | None,
        folder_id: UUID | None,
    ) -> None:
        stmt = (
            update(ThreadDB)
            .where(
                ThreadDB.id.in_(thread_ids),
                ThreadDB.user_id == user_id,
            )
            .values(project_id=project_id, folder_id=folder_id)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        await self.db.execute(stmt)

    async def take_complete_on_success(self, thread_id: str) -> bool:
        """Clear the thread's auto-completion flag; True if it was set."""
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id, ThreadDB.complete_on_success.is_(True))
            .values(complete_on_success=False)
            .returning(ThreadDB.id)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ThreadDB.workspace_id == self.workspace_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def set_completed_at(
        self, thread_id: str, completed_at: datetime | None
    ) -> None:
        stmt = (
            update(ThreadDB)
            .where(ThreadDB.id == thread_id)
            .values(completed_at=completed_at)
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

    async def list_for_agent(
        self,
        agent_id: UUID,
        page: PageParams,
        viewer_id: UUID,
    ):
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
                self._is_unread().label("is_unread"),
            )
            .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
            .join(UserDB, ThreadDB.user_id == UserDB.id)
            .where(ThreadDB.agent_id == agent_id)
            .order_by(ThreadDB.created_at.desc(), ThreadDB.id)
        )
        stmt = self._join_read_state(stmt, viewer_id)
        stmt = self._scope(stmt)
        result, total = await self.paginate(stmt, page)
        return result.all(), total
