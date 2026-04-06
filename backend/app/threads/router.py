from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB
from app.agents.runtime import AgentRuntime
from app.agents.stream import _serialize_lc_message
from app.auth.dependencies import get_current_user
from app.database import get_db, get_psycopg_conn_string
from app.threads.models import ThreadCreate, ThreadDB, ThreadRead
from app.threads.serialization import deserialize_to_ui_messages
from app.threads.service import get_thread
from app.users.models import UserDB


router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("/{thread_id}")
async def read_thread(thread_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(
        select(ThreadDB, AgentDB.name, AgentDB.emoji, AgentDB.color, AgentDB.is_archived)
        .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
        .where(ThreadDB.id == thread_id)
    )
    row = result.one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")

    thread, agent_name, agent_emoji, agent_color, agent_archived = row
    thread_read = ThreadRead.model_validate(
        thread, update={
            "agent_name": agent_name,
            "agent_emoji": agent_emoji,
            "agent_color": agent_color,
            "agent_archived": agent_archived,
        }
    )

    async with AsyncPostgresSaver.from_conn_string(
        get_psycopg_conn_string()
    ) as checkpointer:
        checkpoint = await checkpointer.aget(
            config={"configurable": {"thread_id": thread_id}}
        )

        if checkpoint:
            channel_values = checkpoint["channel_values"]
            lc_messages = channel_values.get("messages", [])
            todos = channel_values.get("todos", [])
            values: dict = {
                "messages": [_serialize_lc_message(m) for m in lc_messages],
            }
            if todos:
                values["todos"] = todos
            return {
                "messages": deserialize_to_ui_messages(lc_messages),
                "values": values,
                "thread": thread_read,
            }
        else:
            return {"messages": [], "values": {"messages": []}, "thread": thread_read}


@router.get("/{thread_id}/subagents/{tool_call_id}/state")
async def get_subagent_state(thread_id: str, tool_call_id: str) -> dict:
    """Fetch a subagent's checkpoint state (its internal messages) by tool call ID."""
    async with AsyncPostgresSaver.from_conn_string(
        get_psycopg_conn_string()
    ) as checkpointer:
        checkpoint = await checkpointer.aget(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": f"tools:{tool_call_id}",
                }
            }
        )

        if not checkpoint:
            return {"messages": [], "values": {}}

        channel_values = checkpoint["channel_values"]
        lc_messages = channel_values.get("messages", [])
        return {
            "messages": [_serialize_lc_message(m) for m in lc_messages],
        }


@router.get("/")
async def get_threads(
    db: AsyncSession = Depends(get_db), current_user: UserDB = Depends(get_current_user)
) -> list[ThreadRead]:
    result = await db.execute(
        select(ThreadDB, AgentDB.name, AgentDB.emoji, AgentDB.color, AgentDB.is_archived)
        .join(AgentDB, ThreadDB.agent_id == AgentDB.id)
        .where(ThreadDB.user_id == current_user.id)
        .order_by(ThreadDB.created_at.desc())
    )
    rows = result.all()
    return [
        ThreadRead.model_validate(
            thread, update={
                "agent_name": agent_name,
                "agent_emoji": agent_emoji,
                "agent_color": agent_color,
                "agent_archived": agent_archived,
            })
        for thread, agent_name, agent_emoji, agent_color, agent_archived in rows
    ]


@router.post("/")
async def create_thread(
    thread_data: ThreadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
) -> ThreadRead:
    # Exclude None id so ThreadDB uses its default_factory
    thread_dict = thread_data.model_dump(exclude_none=True)
    thread = ThreadDB(**thread_dict, user_id=current_user.id)
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return ThreadRead.model_validate(thread)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, db: AsyncSession = Depends(get_db)) -> None:

    async with AsyncPostgresSaver.from_conn_string(
        get_psycopg_conn_string()
    ) as checkpointer:
        await checkpointer.adelete_thread(thread_id=thread_id)

    result = await db.execute(select(ThreadDB).where(ThreadDB.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    await db.delete(thread)
    await db.commit()


@router.post("/{thread_id}/runs/stream")
async def run_stream(
    thread=Depends(get_thread),
    input: dict | None = Body(None, embed=True),
    command: dict | None = Body(None, embed=True),
    config: dict | None = Body(None, embed=True),
    context: dict | None = Body(None, embed=True),
    user_id: str = Depends(get_current_user),
    db=Depends(get_db),
):
    """LangGraph native streaming endpoint for @langchain/langgraph-sdk useStream."""
    runtime = await AgentRuntime.build(thread=thread, db=db)

    # Extract trigger from config.configurable if provided
    trigger = None
    config_overrides = None
    if config and config.get("configurable"):
        trigger = config["configurable"].pop("trigger", None)
        # thread_id is already from the URL path, remove it from config
        config["configurable"].pop("thread_id", None)
        if config["configurable"]:
            config_overrides = config

    return StreamingResponse(
        runtime.stream(
            input=input,
            command=command,
            trigger=trigger,
            config_overrides=config_overrides,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
