"""Agent Streaming Protocol HTTP surface (see package docstring).

Default `@langchain/langgraph-sdk` `HttpAgentServerAdapter` paths are served
as-is — `/threads/{id}/commands`, `/threads/{id}/stream/events`,
`/threads/{id}/state` — so the frontend needs no `paths` override, only the
`/api/backend` proxy prefix in `apiUrl`.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.protocol.schemas import EventStreamBody, ProtocolCommand
from app.agents.protocol.service import ProtocolService
from app.agents.runs.router import authorize_thread, get_run_service
from app.agents.runs.service import RunService
from app.auth.dependencies import get_current_user  # noqa: F401 — via authorize_thread
from app.database import get_db
from app.mcp.client.responses import oauth_required_response
from app.redis_client import get_redis
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
    runs: RunService = Depends(get_run_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: same session auth used
):
    """Execute one protocol command against the thread."""
    # Same OAuth pre-flight as the legacy run endpoints: refuse to launch
    # when a bound MCP server needs (re)authorization, answering the same
    # 401 body the frontend's connect affordance consumes. Covers resumes
    # too — a thread can sit at an interrupt long enough for OAuth to
    # expire, and the legacy endpoints re-check on both paths.
    if command.method in ("run.start", "input.respond") and (
        auth_url := await runs.required_oauth_url(
            db, thread.agent_id, str(thread.user_id)
        )
    ):
        return oauth_required_response(auth_url)
    # Auth queries are done — release the pooled connection before RunService
    # opens its own sessions (holding both risks pool starvation).
    await db.commit()
    return await service.dispatch(thread_id, str(thread.user_id), command)


@router.post("/stream/events")
async def stream_events(
    thread_id: str,
    body: EventStreamBody,
    _: ThreadResponse = Depends(authorize_thread),
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
    _: ThreadResponse = Depends(authorize_thread),
) -> list[dict]:
    """Checkpoint history (LangGraph `client.threads.getHistory` shape).

    Served empty on purpose: the client uses history pages only to promote
    historical subagent namespaces (reading pregel task internals this
    facade does not reconstruct), and it treats an empty page as "nothing
    to promote" — the web app's own subagent-state fallback endpoint covers
    viewing those conversations. Answering `[]` instead of 404 keeps the
    client's discovery seed quiet."""
    return []


@router.get("/state")
async def get_state(
    thread_id: str,
    _: ThreadResponse = Depends(authorize_thread),
    service: ProtocolService = Depends(get_protocol_service),
) -> dict:
    """LangGraph-shaped state snapshot (`values` / `next` / `tasks`) for
    client hydration. Served raw (never camelized) — the protocol client
    fetches it outside the axios interceptor."""
    return await service.thread_state(thread_id)
