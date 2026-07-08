"""HTTP surface for the durable runtime, nested under a thread.

`POST /stream` (create + subscribe) preserves the exact SSE wire shape the
frontend already consumes — it just adds an `X-Run-Id` header and the run now
outlives the request. `GET /{run_id}/stream` reattaches to a live or finished run
by replaying its event log from a cursor.
"""

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runs.schemas import RunCreate, RunResponse
from app.agents.runs.service import RunService
from app.agents.runs.state import RunStatus
from app.agents.runtime import read_run_result
from app.agents.structured_output import validate_structured_response
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.exceptions import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    StructuredOutputError,
)
from app.redis_client import get_redis
from app.threads.schemas import ThreadResponse
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


router = APIRouter(prefix="/threads/{thread_id}/runs", tags=["runs"])

# User-level surface (not nested under a thread).
user_runs_router = APIRouter(prefix="/runs", tags=["runs"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def get_run_service() -> RunService:
    return RunService(get_redis())


def _parse_run_config(config: dict | None) -> tuple[str | None, dict | None]:
    """Pull `trigger` and `config_overrides` out of a /runs request body config.

    Consumes `trigger` and `thread_id` from `config["configurable"]` and returns
    `(trigger, config_overrides)`, where `config_overrides` is the remainder (or
    None if empty).
    """
    if not config or not config.get("configurable"):
        return None, None
    trigger = config["configurable"].pop("trigger", None)
    config["configurable"].pop("thread_id", None)
    config_overrides = config if config["configurable"] else None
    return trigger, config_overrides


async def authorize_thread(
    thread_id: str,
    current_user: UserDB = Depends(get_current_user),
    service: ThreadService = Depends(get_thread_service),
) -> ThreadResponse:
    """Load the thread and require the caller to own it (404 if missing, 403 if not)."""
    thread = await service.get(thread_id)
    if thread.user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to access this thread")
    return thread


def _ensure_run_on_thread(record, thread_id: str) -> None:
    """A run id from another thread must not leak across the nested route."""
    if record.thread_id != thread_id:
        raise NotFoundError("Run not found")


@user_runs_router.get("/active", response_model=list[RunResponse])
async def list_active_runs(
    recent_seconds: int = Query(0, ge=0, le=3600),
    current_user: UserDB = Depends(get_current_user),
    service: RunService = Depends(get_run_service),
) -> list[RunResponse]:
    """The caller's in-flight runs across all threads — one aggregate read
    backing the sidebar activity indicator (poll this, not per-thread).

    `recent_seconds` widens the read to runs that finished within that window,
    letting pollers observe error/success transitions between polls."""
    records = await service.list_active_for_user(
        str(current_user.id), recent_seconds=recent_seconds
    )
    return [RunResponse.from_record(r) for r in records]


@router.post("/stream")
async def create_run_stream(
    thread_id: str,
    agent_input: dict | None = Body(None, embed=True, alias="input"),
    command: dict | None = Body(None, embed=True),
    config: dict | None = Body(None, embed=True),
    thread: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: same session auth used
):
    """Create a run and stream it. Same SSE protocol as before; durable underneath."""
    trigger, config_overrides = _parse_run_config(config)
    record = await runs.create(
        thread_id=thread_id,
        user_id=str(thread.user_id),
        input=agent_input,
        command=command,
        trigger=trigger,
        config_overrides=config_overrides,
    )
    # Release the pooled connection before the response streams for the whole
    # run — auth queries are done; RunService uses its own short-lived sessions.
    await db.commit()
    return StreamingResponse(
        runs.stream(record.id),
        media_type="text/event-stream",
        headers={**_SSE_HEADERS, "X-Run-Id": record.id},
    )


@router.post("/invoke")
async def invoke_run(
    thread_id: str,
    agent_input: dict | None = Body(None, embed=True, alias="input"),
    command: dict | None = Body(None, embed=True),
    config: dict | None = Body(None, embed=True),
    output_schema: dict | None = Body(None, embed=True),
    thread: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: same session auth used
) -> dict:
    """Create a run and block until it finishes, returning the final answer.

    Same durable run as `/stream`; the open HTTP connection is just a consumer
    that awaits the terminal result (and `structured_response`, when
    `output_schema` is given) instead of relaying the live stream.
    """
    trigger, config_overrides = _parse_run_config(config)
    record = await runs.create(
        thread_id=thread_id,
        user_id=str(thread.user_id),
        input=agent_input,
        command=command,
        trigger=trigger,
        config_overrides=config_overrides,
        output_schema=output_schema,
    )
    # Release the pooled connection before blocking for the whole run — auth
    # queries are done; RunService uses its own short-lived sessions.
    await db.commit()
    record = await runs.wait_for_terminal(record.id)
    # Only a clean success yields a result. cancelled/interrupted/error/timeout
    # would otherwise return stale or partial checkpoint data as if it succeeded.
    if record.status is not RunStatus.success:
        raise DomainError(
            record.error or f"Run did not complete ({record.status.value})"
        )
    result = await read_run_result(thread_id)
    # Backstop for paths where the formatting turn never ran (e.g. recursion
    # fallback): the schema contract must hold on everything returned here.
    if output_schema is not None and (
        error := validate_structured_response(
            result["structured_response"], output_schema
        )
    ):
        raise StructuredOutputError(
            f"Run completed without a valid structured response: {error}"
        )
    return result


@router.post("", status_code=201)
async def create_run(
    thread_id: str,
    body: RunCreate,
    thread: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
) -> RunResponse:
    """Create a run without subscribing (caller streams later via `/{run_id}/stream`)."""
    trigger, config_overrides = _parse_run_config(body.config)
    record = await runs.create(
        thread_id=thread_id,
        user_id=str(thread.user_id),
        input=body.input,
        command=body.command,
        trigger=trigger,
        config_overrides=config_overrides,
        multitask_strategy=body.multitask_strategy,
    )
    return RunResponse.from_record(record)


@router.get("")
async def list_runs(
    thread_id: str,
    _: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
) -> list[RunResponse]:
    return [RunResponse.from_record(r) for r in await runs.list_for_thread(thread_id)]


@router.get("/active")
async def get_active_run(
    thread_id: str,
    _: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
) -> RunResponse | None:
    record = await runs.get_active(thread_id)
    return RunResponse.from_record(record) if record else None


@router.get("/{run_id}")
async def read_run(
    thread_id: str,
    run_id: str,
    _: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
) -> RunResponse:
    record = await runs.get(run_id)
    _ensure_run_on_thread(record, thread_id)
    return RunResponse.from_record(record)


@router.get("/{run_id}/stream")
async def stream_run(
    thread_id: str,
    run_id: str,
    last_event_id: str = Query("0"),
    _: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: same session auth used
):
    """Reattach to a run, replaying its event log from `last_event_id`.

    `last_event_id=0` replays the whole turn; the SDK passes the last Redis
    stream id it saw to resume after a reconnect. Works on a finished run too —
    the log (including the `end` sentinel) is replayed in full.
    """
    record = await runs.get(run_id)
    _ensure_run_on_thread(record, thread_id)
    # Release the pooled connection before the response streams for the whole
    # run — auth queries are done; RunService uses its own short-lived sessions.
    await db.commit()
    return StreamingResponse(
        runs.stream(run_id, last_event_id),
        media_type="text/event-stream",
        headers={**_SSE_HEADERS, "X-Run-Id": run_id},
    )


@router.post("/{run_id}/cancel")
async def cancel_run(
    thread_id: str,
    run_id: str,
    _: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
) -> RunResponse:
    record = await runs.get(run_id)
    _ensure_run_on_thread(record, thread_id)
    return RunResponse.from_record(await runs.cancel(run_id))
