from fastapi import APIRouter, Depends, Request

from app.agents.core.service import AgentService, get_agent_service
from app.agents.stream import _serialize_lc_message
from app.agents.structured_output import is_structured_output_artifact
from app.auth.dependencies import detect_auth_method, get_current_user
from app.database import get_checkpointer
from app.exceptions import PermissionDeniedError
from app.threads.models import ThreadDB, ThreadSource
from app.threads.schemas import ThreadCreate, ThreadPatch, ThreadResponse, ViewerRole
from app.threads.serialization import deserialize_to_ui_messages, pending_interrupt
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


router = APIRouter(prefix="/threads", tags=["threads"])


async def _resolve_viewer_role(
    thread: ThreadDB,
    current_user: UserDB,
    agent_service: AgentService,
) -> ViewerRole | None:
    """Return the viewer's role on this thread, or raise 403.

    - Owner of the thread → ``None`` (full access).
    - Workspace admin or per-agent owner/admin → ``"admin"`` (read-only).
    - Anyone else → ``PermissionDeniedError``.
    """
    if thread.user_id == current_user.id:
        return None
    agent = await agent_service.get(
        thread.agent_id, user_id=current_user.id, user_role=current_user.role
    )
    if agent.current_user_permission in ("owner", "admin"):
        return "admin"
    raise PermissionDeniedError("Not authorized to view this thread")


@router.get("/{thread_id}")
async def read_thread(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> dict:
    thread = await service.get(thread_id)
    viewer_role = await _resolve_viewer_role(thread, current_user, agent_service)
    thread_read = await service.get_with_agent(thread_id)

    async with get_checkpointer() as checkpointer:
        checkpoint_tuple = await checkpointer.aget_tuple(
            config={"configurable": {"thread_id": thread_id}}
        )

        if checkpoint_tuple is None:
            return {
                "messages": [],
                "values": {"messages": []},
                "thread": thread_read,
                "interrupted": False,
                "viewer_role": viewer_role,
            }

        channel_values = checkpoint_tuple.checkpoint["channel_values"]
        # Formatting-turn artifacts (raw-JSON message or synthetic tool-call
        # pair) are chat-history noise: the parsed object is exposed under
        # values["structured_response"] instead.
        lc_messages = [
            m
            for m in channel_values.get("messages", [])
            if not is_structured_output_artifact(m)
        ]
        todos = channel_values.get("todos", [])
        values: dict = {
            "messages": [_serialize_lc_message(m) for m in lc_messages],
        }
        if todos:
            values["todos"] = todos
        if (structured := channel_values.get("structured_response")) is not None:
            values["structured_response"] = structured

        interrupt_value = pending_interrupt(checkpoint_tuple)

        return {
            "messages": deserialize_to_ui_messages(lc_messages),
            "values": values,
            "thread": thread_read,
            "interrupted": interrupt_value is not None,
            "interrupt_value": interrupt_value,
            "viewer_role": viewer_role,
        }


def _task_description(messages: list, tool_call_id: str) -> str | None:
    """Return the ``description`` arg of the ``task`` tool call with this id.

    The subagent is seeded with a ``HumanMessage(content=description)``, so the
    description is what links a parent tool call to its subgraph checkpoint.
    """
    for msg in messages:
        for tc in getattr(msg, "tool_calls", None) or []:
            if tc.get("id") == tool_call_id:
                return (tc.get("args") or {}).get("description")
    return None


def _seed_human_content(messages: list) -> str | None:
    """Return the text content of a subgraph's seed (first) message, if any."""
    if not messages:
        return None
    content = getattr(messages[0], "content", None)
    return content if isinstance(content, str) else None


@router.get("/{thread_id}/subagents/{tool_call_id}/state")
async def get_subagent_state(thread_id: str, tool_call_id: str) -> dict:
    """Fetch a subagent's checkpoint state (its internal messages) by tool call ID.

    A subagent runs as a Pregel subgraph whose checkpoint namespace is keyed by an
    internal task id — not the ``tool_call_id`` used to invoke it. So we can't look
    it up directly. Instead we resolve the namespace the way the frontend SDK does
    while streaming: match the ``task`` tool call's ``description`` against each
    subgraph checkpoint's seed message.
    """
    async with get_checkpointer() as checkpointer:
        # The task call's description lives in the parent (root-namespace) state.
        parent = await checkpointer.aget_tuple(
            config={"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        )
        description = (
            _task_description(
                parent.checkpoint["channel_values"].get("messages", []), tool_call_id
            )
            if parent
            else None
        )

        # alist() with only thread_id walks every namespace's checkpoints
        # newest-first; the first time we see a namespace is its latest checkpoint.
        # The subagent's seed message is `HumanMessage(content=description)`, so it
        # equals the task call's description exactly — match strictly. A substring
        # match would risk picking the wrong subagent when one description contains
        # another.
        lc_messages: list = []
        if description:
            seen_ns: set[str] = set()
            async for ct in checkpointer.alist(
                config={"configurable": {"thread_id": thread_id}}
            ):
                ns = ct.config["configurable"].get("checkpoint_ns") or ""
                if not ns or ns in seen_ns:
                    continue
                seen_ns.add(ns)
                ns_messages = ct.checkpoint["channel_values"].get("messages", [])
                if _seed_human_content(ns_messages) == description:
                    lc_messages = ns_messages
                    break

        # Legacy fallback: threads that stored state under tools:{tool_call_id}.
        if not lc_messages:
            checkpoint = await checkpointer.aget(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": f"tools:{tool_call_id}",
                    }
                }
            )
            if checkpoint:
                lc_messages = checkpoint["channel_values"].get("messages", [])

        return {"messages": [_serialize_lc_message(m) for m in lc_messages]}


@router.get("/")
async def get_threads(
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> list[ThreadResponse]:
    return await service.list(current_user.id)


@router.post("/")
async def create_thread(
    thread_data: ThreadCreate,
    request: Request,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> ThreadResponse:
    source = (
        ThreadSource.web
        if detect_auth_method(request, current_user) == "cookie"
        else ThreadSource.api
    )
    return await service.create(thread_data, current_user.id, source)


@router.patch("/{thread_id}")
async def update_thread(
    thread_id: str,
    data: ThreadPatch,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> ThreadResponse:
    thread = await service.get(thread_id)
    if thread.user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to edit this thread")
    return await service.update(thread_id, data)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> None:
    thread = await service.get(thread_id)
    if thread.user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to delete this thread")
    async with get_checkpointer() as checkpointer:
        await checkpointer.adelete_thread(thread_id=thread_id)

    await service.delete(thread_id)
