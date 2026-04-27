from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.exceptions import NotFoundError
from app.service import BaseService
from app.threads.models import ThreadDB
from app.threads.repository import ThreadRepository
from app.threads.schemas import ThreadCreate, ThreadResponse


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


class ThreadService(BaseService[ThreadDB, ThreadRepository]):
    not_found_message = "Thread not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, ThreadRepository(db))

    async def get_thread(self, thread_id: str) -> ThreadDB:
        return await self.get_or_404(thread_id)

    async def get_thread_with_agent(self, thread_id: str) -> ThreadResponse:
        row = await self.repository.get_with_agent(thread_id)
        if not row:
            raise NotFoundError(self.not_found_message)
        return _thread_with_agent(*row)

    async def list_threads(self, user_id: UUID) -> list[ThreadResponse]:
        rows = await self.repository.list_for_user(user_id)
        return [_thread_with_agent(*row) for row in rows]

    async def create_thread(self, data: ThreadCreate, user_id: UUID) -> ThreadResponse:
        thread = ThreadDB(
            **data.model_dump(exclude_none=True),
            user_id=user_id,
        )
        self.db.add(thread)
        await self.db.flush()
        await self.db.refresh(thread)
        return ThreadResponse.model_validate(thread)

    async def delete_thread(self, thread_id: str) -> ThreadDB:
        thread = await self.get_or_404(thread_id)
        await self.db.delete(thread)
        return thread


def get_thread_service(db: AsyncSession = Depends(get_db)) -> ThreadService:
    return ThreadService(db)


async def get_or_create_thread(
    ts: str, agent_id: str, question: str, user_id: str,
) -> tuple[ThreadDB, AsyncSession]:
    """Slack-side helper: open a dedicated session and return/persist the thread.

    Uses its own session because Slack event handlers don't run inside a FastAPI
    request, so they can't rely on the request-scoped ``get_db``.
    """
    db = AsyncSessionLocal()
    thread = await db.get(ThreadDB, ts)
    if thread is None:
        thread = ThreadDB(
            id=ts,
            agent_id=agent_id,
            model_id="deepseek-v4-flash",
            first_message_content=question,
            user_id=user_id,
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
    return thread, db
