from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException
from app.database import AsyncSessionLocal, get_db
from app.threads.models import ThreadDB


async def get_thread(thread_id: str, db: AsyncSession = Depends(get_db)) -> ThreadDB:
    result = await db.execute(
        select(ThreadDB).where(ThreadDB.id == thread_id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


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
