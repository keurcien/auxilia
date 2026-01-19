import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.adapters.message_adapter import deserialize_to_ui_messages
from app.agents.runtime import AgentRuntime
from app.database import get_db
from app.models.message import Message
from app.users.models import UserDB
from app.auth.dependencies import get_current_user
from app.threads.models import ThreadCreate, ThreadDB, ThreadRead
from app.agents.runtime import AgentRuntimeDependencies, ChatModelFactory

DB_URI = "postgresql://auxilia:auxilia@localhost:5432/auxilia"

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("/{thread_id}")
async def read_thread(thread_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(
        select(ThreadDB).where(ThreadDB.id == uuid.UUID(thread_id))
    )
    thread = result.scalar_one_or_none()

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpoint = await checkpointer.aget(
            config={"configurable": {"thread_id": thread_id}}
        )

        if checkpoint:
            return {
                "messages": deserialize_to_ui_messages(
                    checkpoint["channel_values"]["messages"]
                ),
                "thread": ThreadRead.model_validate(thread),
            }
        else:
            return {"messages": [], "thread": ThreadRead.model_validate(thread)}


@router.get("/")
async def get_threads(db: AsyncSession = Depends(get_db), current_user: UserDB = Depends(get_current_user)) -> list[ThreadRead]:
    result = await db.execute(select(ThreadDB).where(ThreadDB.user_id == current_user.id).order_by(ThreadDB.created_at.desc()))
    threads = result.scalars().all()
    return [ThreadRead.model_validate(thread) for thread in threads]


@router.post("/")
async def create_thread(
    thread_data: ThreadCreate, db: AsyncSession = Depends(get_db), current_user: UserDB = Depends(get_current_user)
) -> ThreadRead:
    thread = ThreadDB(**thread_data.model_dump(), user_id=current_user.id)
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return ThreadRead.model_validate(thread)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, db: AsyncSession = Depends(get_db)) -> None:

    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        await checkpointer.adelete_thread(thread_id=thread_id)
    
    result = await db.execute(
        select(ThreadDB).where(ThreadDB.id == uuid.UUID(thread_id))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    await db.delete(thread)
    await db.commit()


async def get_thread(thread_id: str, db: AsyncSession = Depends(get_db)) -> ThreadDB:
    result = await db.execute(
        select(ThreadDB).where(ThreadDB.id == uuid.UUID(thread_id))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread

@router.post("/{thread_id}/invoke")
async def invoke(
    thread=Depends(get_thread),
    messages: list[Message] = Body(..., embed=True),
    messageId: str | None = Body(None, embed=True),
    db=Depends(get_db)
):
    deps = AgentRuntimeDependencies(
        model_factory=ChatModelFactory(),
    )
    agent_runtime = await AgentRuntime.create(thread=thread, db=db, deps=deps)
    

    return StreamingResponse(
        agent_runtime.stream(messages, message_id=messageId),
        media_type="text/plain",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )