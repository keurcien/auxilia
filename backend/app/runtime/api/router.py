"""Agent Streaming Protocol HTTP surface (see package docstring).

Default `@langchain/langgraph-sdk` `HttpAgentServerAdapter` paths are served
as-is — `/threads/{id}/commands`, `/threads/{id}/stream/events`,
`/threads/{id}/state` — so the frontend needs no `paths` override, only the
`/api/backend` proxy prefix in `apiUrl`.

Authorization: the read endpoints (`/state`, `/history`, `/messages/{id}`,
`/stream/events`) accept the thread's owner *and* an admin of its agent
(`authorize_thread_read`) — the same audience `GET /threads/{id}` serves, so an
admin's read-only view hydrates. `/commands` stays owner-only.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user  # noqa: F401 — via authorize_thread
from app.database import get_db
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.mcp.client.responses import oauth_required_response
from app.redis_client import get_redis
from app.runtime.api.schemas import EventStreamBody, HistoryBody, ProtocolCommand
from app.runtime.api.service import ProtocolService
from app.runtime.runs.router import authorize_thread
from app.threads.dependencies import authorize_thread_read
from app.threads.models import ThreadDB
from app.threads.schemas import ThreadResponse


router = APIRouter(prefix="/threads/{thread_id}", tags=["protocol"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def get_protocol_service() -> ProtocolService:
    return ProtocolService(get_redis())


@router.post("/commands")
async def post_command(
    thread_id: str,
    command: ProtocolCommand,
    thread: ThreadResponse = Depends(authorize_thread),
    service: ProtocolService = Depends(get_protocol_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: same session auth used
):
    """Execute one protocol command against the thread."""
    # Auth queries are done — release the pooled connection before `launch`
    # opens its own sessions (holding both risks pool starvation).
    await db.commit()
    try:
        return await service.dispatch(thread_id, str(thread.user_id), command)
    except OAuthAuthorizationRequired as exc:
        # `run.start` / `input.respond` refused by the launch gate: answer the
        # same 401 body as the run endpoints, which the frontend's connect
        # affordance consumes. Covers resumes too — a thread can sit at an
        # interrupt long enough for OAuth to expire. No run was created.
        return oauth_required_response(exc.url)


@router.post("/stream/events")
async def stream_events(
    thread_id: str,
    body: EventStreamBody,
    _: ThreadDB = Depends(authorize_thread_read),
    service: ProtocolService = Depends(get_protocol_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: same session auth used
):
    """Open one filtered protocol SSE session on the thread."""
    # Release the pooled connection before the response streams indefinitely.
    await db.commit()
    return StreamingResponse(
        service.stream_events(thread_id, body),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/history")
async def get_history(
    thread_id: str,
    body: HistoryBody,
    _: ThreadDB = Depends(authorize_thread_read),
    service: ProtocolService = Depends(get_protocol_service),
) -> list[dict]:
    """Checkpoint history (LangGraph `client.threads.getHistory` shape).

    Root pages are empty; a `checkpoint.checkpoint_ns` of
    `tools:<tool_call_id>` returns that subagent's latest checkpoint, which
    is how the client hydrates an idle thread's subagent cards (see
    `ProtocolService.thread_history`). Served raw, like `/state`."""
    return await service.thread_history(thread_id, body.checkpoint_ns)


@router.get("/state")
async def get_state(
    thread_id: str,
    _: ThreadDB = Depends(authorize_thread_read),
    service: ProtocolService = Depends(get_protocol_service),
) -> dict:
    """LangGraph-shaped state snapshot (`values` / `next` / `tasks`) for
    client hydration. Served raw (never camelized) — the protocol client
    fetches it outside the axios interceptor."""
    return await service.thread_state(thread_id)


@router.get("/messages/{message_id}")
async def get_message(
    thread_id: str,
    message_id: str,
    _: ThreadDB = Depends(authorize_thread_read),
    service: ProtocolService = Depends(get_protocol_service),
) -> dict:
    """One message, whole. `/state` and `/history` ship tool results cut at
    `TOOL_PREVIEW_CHARS`; the client fetches the rest from here on demand.
    Served raw, like `/state`."""
    return await service.message(thread_id, message_id)
