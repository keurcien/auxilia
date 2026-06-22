from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_checkpointer, get_db
from app.exceptions import NotFoundError
from app.service import BaseService
from app.threads.models import ThreadDB, ThreadSource
from app.threads.repository import ThreadRepository
from app.threads.schemas import AgentThreadResponse, ThreadCreate, ThreadResponse


def _thread_with_agent(
    thread: ThreadDB,
    agent_name: str | None,
    agent_emoji: str | None,
    agent_color: str | None,
    agent_archived: bool,
) -> ThreadResponse:
    return ThreadResponse.model_validate(
        thread,
        update={
            "agent_name": agent_name,
            "agent_emoji": agent_emoji,
            "agent_color": agent_color,
            "agent_archived": agent_archived,
        },
    )


def _agent_thread(
    thread: ThreadDB,
    agent_name: str | None,
    agent_emoji: str | None,
    agent_color: str | None,
    agent_archived: bool,
    user_email: str | None,
    user_name: str | None,
) -> AgentThreadResponse:
    return AgentThreadResponse.model_validate(
        thread,
        update={
            "agent_name": agent_name,
            "agent_emoji": agent_emoji,
            "agent_color": agent_color,
            "agent_archived": agent_archived,
            "user_email": user_email,
            "user_name": user_name,
        },
    )


class ThreadService(BaseService[ThreadDB, ThreadRepository]):
    not_found_message = "Thread not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, ThreadRepository(db))

    async def get(self, thread_id: str) -> ThreadDB:
        return await self.get_or_404(thread_id)

    async def get_with_agent(self, thread_id: str) -> ThreadResponse:
        row = await self.repository.get_with_agent(thread_id)
        if not row:
            raise NotFoundError(self.not_found_message)
        return _thread_with_agent(*row)

    async def list(self, user_id: UUID) -> list[ThreadResponse]:
        rows = await self.repository.list_for_user(user_id)
        return [_thread_with_agent(*row) for row in rows]

    async def list_for_agent(
        self, agent_id: UUID
    ) -> list[AgentThreadResponse]:
        rows = await self.repository.list_for_agent(agent_id)
        return [_agent_thread(*row) for row in rows]

    async def create(
        self,
        data: ThreadCreate,
        user_id: UUID,
        source: ThreadSource,
    ) -> ThreadResponse:
        thread = ThreadDB(
            **data.model_dump(exclude_none=True),
            user_id=user_id,
            source=source,
        )
        self.db.add(thread)
        await self.db.flush()
        await self.db.refresh(thread)
        return ThreadResponse.model_validate(thread)

    async def delete(self, thread_id: str) -> ThreadDB:
        thread = await self.get_or_404(thread_id)
        await self.db.delete(thread)
        return thread

    async def delete_all_for_agent(self, agent_id: UUID) -> None:
        """Delete every thread belonging to an agent along with its LangGraph
        checkpoints. Used when an agent is permanently deleted."""
        thread_ids = await self.repository.list_ids_for_agent(agent_id)
        if not thread_ids:
            return
        async with get_checkpointer() as checkpointer:
            for thread_id in thread_ids:
                await checkpointer.adelete_thread(thread_id=thread_id)
        for thread_id in thread_ids:
            thread = await self.repository.get(thread_id)
            if thread is not None:
                await self.db.delete(thread)
        await self.db.flush()

    async def get_or_create(
        self,
        ts: str,
        agent_id: str,
        question: str | None,
        user_id: str,
    ) -> ThreadDB:
        """Return the existing thread or create a new Slack-sourced thread.

        Caller (Slack handler) owns the session lifecycle and the final commit.
        """
        thread = await self.db.get(ThreadDB, ts)
        if thread is None:
            thread = ThreadDB(
                id=ts,
                agent_id=agent_id,
                model_id="deepseek-v4-flash",
                first_message_content=question,
                user_id=user_id,
                source=ThreadSource.slack,
            )
            self.db.add(thread)
            await self.db.flush()
            await self.db.refresh(thread)
        return thread


def get_thread_service(db: AsyncSession = Depends(get_db)) -> ThreadService:
    return ThreadService(db)
