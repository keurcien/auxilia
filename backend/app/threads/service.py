from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_checkpointer, get_db
from app.exceptions import NotFoundError
from app.model_providers.service import ModelService
from app.pagination import Page, PageParams
from app.service import BaseService
from app.threads.models import ThreadDB, ThreadSource
from app.threads.repository import ThreadRepository
from app.threads.schemas import (
    AgentThreadResponse,
    ThreadCreate,
    ThreadPatch,
    ThreadResponse,
)


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
        response = _thread_with_agent(*row)
        response.model_available = await ModelService(self.db).is_available(
            response.model_id
        )
        return response

    async def list(self, user_id: UUID, page: PageParams) -> Page[ThreadResponse]:
        rows, total = await self.repository.list_for_user(user_id, page)
        return Page.build([_thread_with_agent(*row) for row in rows], total, page)

    async def list_for_agent(
        self, agent_id: UUID, page: PageParams
    ) -> Page[AgentThreadResponse]:
        rows, total = await self.repository.list_for_agent(agent_id, page)
        return Page.build([_agent_thread(*row) for row in rows], total, page)

    async def list_for_trigger(
        self, trigger_id: UUID, since: datetime | None = None
    ) -> list[ThreadDB]:
        return await self.repository.list_for_trigger(trigger_id, since=since)

    async def create(
        self,
        data: ThreadCreate,
        user_id: UUID,
        source: ThreadSource,
        trigger_id: UUID | None = None,
    ) -> ThreadResponse:
        # `trigger_id` is a keyword (not a ThreadCreate field) so API clients
        # can't attach arbitrary threads to a trigger — only the scanner sets it.
        thread = ThreadDB(
            **data.model_dump(exclude_none=True),
            user_id=user_id,
            source=source,
            trigger_id=trigger_id,
        )
        self.db.add(thread)
        await self.db.flush()
        await self.db.refresh(thread)
        # Compute (not default) the availability flag: creating a thread on a
        # disabled model is possible via the API, and the schema default
        # (True) must not masquerade as a runnable thread.
        return ThreadResponse.model_validate(
            thread,
            update={
                "model_available": await ModelService(self.db).is_available(
                    thread.model_id
                )
            },
        )

    async def update(self, thread_id: str, data: ThreadPatch) -> ThreadResponse:
        thread = await self.get_or_404(thread_id)
        await self.repository.update(thread, data)
        return await self.get_with_agent(thread_id)

    async def delete(self, thread_id: str) -> ThreadDB:
        thread = await self.get_or_404(thread_id)
        await self.db.delete(thread)
        return thread

    async def delete_rows_for_agent(self, agent_id: UUID) -> list[str]:
        """Bulk-delete an agent's thread rows (one statement) and return their
        ids so the caller can purge LangGraph checkpoints afterwards.

        Checkpoint deletion is intentionally NOT done here: it is an external,
        non-transactional side effect and must run only after all DB deletes
        have succeeded — see ``purge_checkpoints``."""
        thread_ids = await self.repository.list_ids_for_agent(agent_id)
        if thread_ids:
            await self.repository.delete_for_agent(agent_id)
            await self.db.flush()
        return thread_ids

    async def purge_checkpoints(self, thread_ids: list[str]) -> None:
        """Delete the LangGraph checkpoints for the given threads.

        This writes to a separate, auto-committed connection (the checkpointer),
        so it cannot be rolled back with the request transaction. Callers must
        run it last — once every DB delete has succeeded — to avoid leaving
        threads in Postgres without their checkpoints."""
        if not thread_ids:
            return
        async with get_checkpointer() as checkpointer:
            for thread_id in thread_ids:
                await checkpointer.adelete_thread(thread_id=thread_id)

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
            # Slack has no model picker — new threads start on the workspace
            # default (admin-flagged model, else the first available one).
            thread = ThreadDB(
                id=ts,
                agent_id=agent_id,
                model_id=await ModelService(self.db).get_default_model_id(),
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
