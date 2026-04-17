from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.agents.runtime import AgentRuntime
from app.agents.stream import _serialize_lc_message
from app.auth.dependencies import get_current_user
from app.database import get_db, get_psycopg_conn_string
from app.threads.schemas import ThreadCreate, ThreadResponse
from app.threads.serialization import deserialize_to_ui_messages
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("/{thread_id}")
async def read_thread(
    thread_id: str,
    service: ThreadService = Depends(get_thread_service),
) -> dict:
    thread_read = await service.get_thread_with_agent(thread_id)

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
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> list[ThreadResponse]:
    return await service.list_threads(current_user.id)


@router.post("/")
async def create_thread(
    thread_data: ThreadCreate,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> ThreadResponse:
    return await service.create_thread(thread_data, current_user.id)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    service: ThreadService = Depends(get_thread_service),
) -> None:
    async with AsyncPostgresSaver.from_conn_string(
        get_psycopg_conn_string()
    ) as checkpointer:
        await checkpointer.adelete_thread(thread_id=thread_id)

    await service.delete_thread(thread_id)


@router.post("/{thread_id}/runs/stream")
async def run_stream(
    thread_id: str,
    input: dict | None = Body(None, embed=True),
    command: dict | None = Body(None, embed=True),
    config: dict | None = Body(None, embed=True),
    context: dict | None = Body(None, embed=True),  # noqa: ARG001
    user_id: str = Depends(get_current_user),  # noqa: ARG001
    service: ThreadService = Depends(get_thread_service),
    db=Depends(get_db),
):
    """LangGraph native streaming endpoint for @langchain/langgraph-sdk useStream."""
    thread = await service.get_thread(thread_id)
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


@router.post("/{thread_id}/runs/invoke")
async def run_invoke(
    thread_id: str,
    input: dict | None = Body(None, embed=True),
    command: dict | None = Body(None, embed=True),
    config: dict | None = Body(None, embed=True),
    context: dict | None = Body(None, embed=True),  # noqa: ARG001
    user_id: str = Depends(get_current_user),  # noqa: ARG001
    service: ThreadService = Depends(get_thread_service),
    db=Depends(get_db),
):
    """Non-streaming invoke endpoint. Returns the final agent response as JSON."""
    thread = await service.get_thread(thread_id)
    runtime = await AgentRuntime.build(thread=thread, db=db)

    trigger = None
    config_overrides = None
    if config and config.get("configurable"):
        trigger = config["configurable"].pop("trigger", None)
        config["configurable"].pop("thread_id", None)
        if config["configurable"]:
            config_overrides = config

    return await runtime.invoke(
        input=input,
        command=command,
        trigger=trigger,
        config_overrides=config_overrides,
    )
