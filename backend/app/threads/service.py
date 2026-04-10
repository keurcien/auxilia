from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.exceptions import NotFoundError
from app.threads.models import ThreadDB
from app.threads.repository import ThreadRepository
from app.threads.schemas import ThreadCreate, ThreadResponse


class ThreadService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = ThreadRepository(db)

    async def get_thread(self, thread_id: str) -> ThreadDB:
        thread = await self.repository.get(thread_id)
        if not thread:
            raise NotFoundError("Thread not found")
        return thread

    async def get_thread_with_agent(self, thread_id: str) -> ThreadResponse:
        row = await self.repository.get_with_agent(thread_id)
        if not row:
            raise NotFoundError("Thread not found")
        thread, agent_name, agent_emoji, agent_color, agent_archived = row
        return ThreadResponse.model_validate(
            thread,
            update={
                "agent_name": agent_name,
                "agent_emoji": agent_emoji,
                "agent_color": agent_color,
                "agent_archived": agent_archived,
            },
        )

    async def list_threads(self, user_id: UUID) -> list[ThreadResponse]:
        rows = await self.repository.list_for_user(user_id)
        return [
            ThreadResponse.model_validate(
                thread,
                update={
                    "agent_name": agent_name,
                    "agent_emoji": agent_emoji,
                    "agent_color": agent_color,
                    "agent_archived": agent_archived,
                },
            )
            for thread, agent_name, agent_emoji, agent_color, agent_archived in rows
        ]

    async def create_thread(self, data: ThreadCreate, user_id: UUID) -> ThreadResponse:
        thread_dict = data.model_dump(exclude_none=True)
        thread = ThreadDB(**thread_dict, user_id=user_id)
        self.db.add(thread)
        await self.db.commit()
        await self.db.refresh(thread)
        return ThreadResponse.model_validate(thread)

    async def delete_thread(self, thread_id: str) -> ThreadDB:
        thread = await self.repository.get(thread_id)
        if not thread:
            raise NotFoundError("Thread not found")
        await self.db.delete(thread)
        await self.db.commit()
        return thread


def get_thread_service(db: AsyncSession = Depends(get_db)) -> ThreadService:
    return ThreadService(db)


# Standalone helper for Slack integration backward compatibility
async def get_or_create_thread(
    ts: str, agent_id: str, question: str, user_id: str,
) -> tuple[ThreadDB, AsyncSession]:
    """Return an existing thread for *ts*, or create one if it doesn't exist."""
    db = AsyncSessionLocal()
    thread = await db.get(ThreadDB, ts)
    if thread is None:
        thread = ThreadDB(
            id=ts,
            agent_id=agent_id,
            model_id="deepseek-chat",
            first_message_content=question,
            user_id=user_id,
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
    return thread, db
