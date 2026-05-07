"""HTTP surface for runs.

Endpoint shapes match LangGraph Server v1 (PRD §5) so ``@langchain/langgraph-sdk``
clients can talk to us without a fork. The router is intentionally thin: it
does auth + DTO conversion and delegates everything else to ``RunService``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse

from app.agents.runs.schemas import RunCreate, RunResponse
from app.agents.runs.service import (
    RunService,
    get_run_service,
    record_to_response,
)
from app.auth.dependencies import get_current_user
from app.users.models import UserDB


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/threads", tags=["runs"])


# --- create ----------------------------------------------------------------


@router.post("/{thread_id}/runs", status_code=status.HTTP_201_CREATED)
async def create_run(
    thread_id: str,
    body: RunCreate,
    current_user: UserDB = Depends(get_current_user),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    """Create a run without subscribing to its event stream.

    The caller can subscribe later via ``GET /threads/{tid}/runs/{rid}/stream``.
    """
    record = await service.create_run(thread_id, current_user, body)
    return record_to_response(record)


@router.post("/{thread_id}/runs/stream")
async def create_and_stream(
    thread_id: str,
    body: RunCreate,
    request: Request,
    current_user: UserDB = Depends(get_current_user),
    service: RunService = Depends(get_run_service),
) -> StreamingResponse:
    """Create a run and immediately subscribe to its event stream.

    The run keeps executing on disconnect; the client can reattach via
    ``GET /threads/{tid}/runs/{rid}/stream`` with ``last_event_id``.
    """
    record = await service.create_run(thread_id, current_user, body)
    return StreamingResponse(
        _sse(service, record.id, current_user, last_event_id="0", request=request),
        media_type="text/event-stream",
        headers=_sse_headers(record.id),
    )


# --- reattach ---------------------------------------------------------------


@router.get("/{thread_id}/runs/{run_id}/stream")
async def reattach_stream(
    thread_id: str,  # noqa: ARG001 - kept for URL shape; not used in lookup
    run_id: UUID,
    request: Request,
    last_event_id: str = Query("0", alias="last_event_id"),
    current_user: UserDB = Depends(get_current_user),
    service: RunService = Depends(get_run_service),
) -> StreamingResponse:
    """Subscribe to an existing run's event stream from the given offset.

    ``last_event_id="0"`` replays from the beginning. The SDK passes the most
    recent ID it has seen so reconnects don't drop events.
    """
    return StreamingResponse(
        _sse(
            service,
            run_id,
            current_user,
            last_event_id=last_event_id,
            request=request,
        ),
        media_type="text/event-stream",
        headers=_sse_headers(run_id),
    )


# --- read / list / cancel ---------------------------------------------------


@router.get("/{thread_id}/runs")
async def list_runs(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: RunService = Depends(get_run_service),
) -> list[RunResponse]:
    return await service.list_runs(thread_id, current_user)


@router.get("/{thread_id}/runs/active")
async def get_active_run(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: RunService = Depends(get_run_service),
) -> RunResponse | None:
    """Return the currently active run on the thread, if any.

    Used by the SDK on page mount to decide whether to reattach.
    """
    record = await service.get_active_run(thread_id, current_user)
    return record_to_response(record) if record is not None else None


@router.get("/{thread_id}/runs/{run_id}")
async def get_run(
    thread_id: str,  # noqa: ARG001
    run_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    record = await service.get_run(run_id, current_user)
    return record_to_response(record)


@router.post("/{thread_id}/runs/{run_id}/cancel")
async def cancel_run(
    thread_id: str,  # noqa: ARG001
    run_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    record = await service.cancel_run(run_id, current_user)
    return record_to_response(record)


# --- SSE helpers ------------------------------------------------------------


_SSE_KEEPALIVE_INTERVAL: float = 15.0


def _sse_headers(run_id: UUID) -> dict[str, str]:
    return {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        # Echo the run id so the SDK can correlate even before reading the body.
        "X-Run-Id": str(run_id),
    }


async def _sse(
    service: RunService,
    run_id: UUID,
    current_user: UserDB,
    *,
    last_event_id: str,
    request: Request,
) -> AsyncIterator[bytes]:
    """Translate Redis Stream events into the LangGraph-Server SSE wire format.

    Two event categories arrive on the Redis stream:

    - ``{"type": "chunk", "data": <encoded SSE str>}`` — pre-encoded by the
      worker via ``LangGraphStreamAdapter``. Forwarded verbatim.
    - everything else (``end``, ``interrupt``, ``error``) — emitted as a
      generic SSE event by name, payload as JSON.

    The SSE Stream ID is exposed as the SSE ``id:`` field so reconnect can
    resume cleanly.
    """
    try:
        async for stream_id, event in service.stream_events(
            run_id, current_user, last_event_id=last_event_id
        ):
            if await request.is_disconnected():
                # Client gave up; the run keeps executing on the worker.
                return
            event_type = event.get("type")
            if event_type == "chunk":
                # ``data`` is already an SSE-encoded block (event:/data:/blank).
                # We prefix the SSE id: line so the SDK can reattach precisely.
                payload = event.get("data") or ""
                yield f"id: {stream_id}\n".encode()
                yield payload.encode() if isinstance(payload, str) else payload
            else:
                yield _encode_sse_event(stream_id, event_type or "message", event)
            if event_type == "end":
                return
    except asyncio.CancelledError:
        # Client disconnected mid-read; don't bubble up — the run survives.
        return


def _encode_sse_event(stream_id: str, event_name: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, default=str)
    return f"id: {stream_id}\nevent: {event_name}\ndata: {body}\n\n".encode()
