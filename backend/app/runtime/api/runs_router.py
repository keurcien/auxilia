"""HTTP surface for the durable runtime, nested under a thread.

Run CRUD, `/invoke` (create + block for the result), `/cancel`, and the
`/runs/active` poll. Live streaming is the Agent Streaming Protocol's job:
`POST /threads/{id}/commands` starts runs and `POST /threads/{id}/stream/events`
relays their event log (`app/runtime/api/protocol_router.py`).
"""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.exceptions import (
    DomainError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    StructuredOutputError,
)
from app.mcp.client.responses import oauth_required_response
from app.redis_client import get_redis
from app.runtime.agent import read_run_result
from app.runtime.middleware.structured_output import validate_structured_response
from app.runtime.runs.schemas import (
    QueuedPromptCreate,
    QueuedPromptOrder,
    QueuedPromptPatch,
    QueuedPromptResponse,
    RunCreate,
    RunResponse,
    queued_prompt_input,
)
from app.runtime.runs.service import RunService
from app.runtime.runs.state import RunStatus
from app.threads.schemas import ThreadResponse
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id


router = APIRouter(prefix="/threads/{thread_id}/runs", tags=["runs"])

# User-level surface (not nested under a thread).
user_runs_router = APIRouter(prefix="/runs", tags=["runs"])


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


async def authorize_thread_for_run_service(
    thread: ThreadResponse = Depends(authorize_thread),
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Release the auth transaction before RunService opens its own session."""
    await db.commit()
    return thread


def _ensure_run_on_thread(record, thread_id: str) -> None:
    """A run id from another thread must not leak across the nested route."""
    if record.thread_id != thread_id:
        raise NotFoundError("Run not found")


def _queued_responses(records) -> list[QueuedPromptResponse]:
    return [
        response
        for record in records
        if (response := QueuedPromptResponse.from_record(record)) is not None
    ]


@user_runs_router.get("/active", response_model=list[RunResponse])
async def list_active_runs(
    recent_seconds: int = Query(0, ge=0, le=3600),
    current_user: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: RunService = Depends(get_run_service),
    db: AsyncSession = Depends(get_db),
) -> list[RunResponse]:
    """The caller's in-flight runs across all threads — one aggregate read
    backing the sidebar activity indicator (poll this, not per-thread).

    `recent_seconds` widens the read to runs that finished within that window,
    letting pollers observe error/success transitions between polls."""
    user_id = str(current_user.id)
    await db.commit()
    records = await service.list_active_for_user(
        user_id, workspace_id, recent_seconds=recent_seconds
    )
    return [RunResponse.from_record(r) for r in records]


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

    Same durable run the protocol's `run.start` creates; the open HTTP
    connection is just a consumer that awaits the terminal result (and
    `structured_response`, when `output_schema` is given) instead of relaying
    the live stream.
    """
    # Pre-flight: refuse to launch if the agent or a subagent needs OAuth; the
    # gate commits/releases the pooled connection itself before probing, so no
    # run is created when authorization is missing and no connection is held
    # during network IO.
    if auth_url := await runs.required_oauth_url(
        db, thread.agent_id, str(thread.user_id), thread.workspace_id
    ):
        # Explicit at the call site: this used to be an exception the
        # app-global handler turned into a response on *any* endpoint that
        # touched MCP (design review §2.4).
        return oauth_required_response(auth_url)
    # Auth queries are done — release the pooled connection before anything
    # else (RunService opens its own sessions; holding both risks pool
    # starvation) and before blocking for the whole run.
    await db.commit()
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
    record = await runs.wait_for_terminal(record.id)
    # Only a clean success yields a result. cancelled/interrupted/error/timeout
    # would otherwise return stale or partial checkpoint data as if it succeeded.
    if record.status is not RunStatus.success:
        raise DomainError(
            record.error or f"Run did not complete ({record.status.value})"
        )
    result = await read_run_result(thread.workspace_id, thread_id)
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
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    """Create a run without subscribing (a protocol event-stream session on the
    thread picks it up as the thread's newest run)."""
    # Pre-flight: refuse to launch if the agent or a subagent needs OAuth,
    # before the run is created.
    if auth_url := await runs.required_oauth_url(
        db, thread.agent_id, str(thread.user_id), thread.workspace_id
    ):
        # Explicit at the call site: this used to be an exception the
        # app-global handler turned into a response on *any* endpoint that
        # touched MCP (design review §2.4).
        return oauth_required_response(auth_url)
    # Release the pooled connection before RunService opens its own session
    # (holding both risks pool starvation), matching /invoke.
    await db.commit()
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
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> list[RunResponse]:
    return [
        RunResponse.from_record(r)
        for r in await runs.list_for_thread(thread_id, thread.workspace_id)
    ]


@router.get("/active")
async def get_active_run(
    thread_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> RunResponse | None:
    record = await runs.get_active(thread_id, thread.workspace_id)
    return RunResponse.from_record(record) if record else None


@router.get("/queue")
async def list_prompt_queue(
    thread_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> list[QueuedPromptResponse]:
    return _queued_responses(
        await runs.list_queued_prompts(thread_id, thread.workspace_id)
    )


@router.post("/queue", status_code=201)
async def enqueue_prompt(
    thread_id: str,
    body: QueuedPromptCreate,
    thread: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
    db: AsyncSession = Depends(get_db),
) -> QueuedPromptResponse:
    text = body.text.strip()
    if not text:
        raise DomainValidationError("A queued prompt cannot be empty.")
    if auth_url := await runs.required_oauth_url(
        db, thread.agent_id, str(thread.user_id), thread.workspace_id
    ):
        return oauth_required_response(auth_url)
    await db.commit()
    record = await runs.create(
        thread_id=thread_id,
        user_id=str(thread.user_id),
        input=queued_prompt_input(text),
        multitask_strategy="enqueue",
    )
    response = QueuedPromptResponse.from_record(record)
    if response is None:  # construction above guarantees this shape
        raise DomainError("Could not project queued prompt")
    return response


@router.patch("/queue/{run_id}")
async def update_prompt_queue_item(
    thread_id: str,
    run_id: str,
    body: QueuedPromptPatch,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> QueuedPromptResponse:
    text = body.text.strip()
    if not text:
        raise DomainValidationError("A queued prompt cannot be empty.")
    record = await runs.get(run_id, thread.workspace_id)
    _ensure_run_on_thread(record, thread_id)
    updated = await runs.update_queued_prompt(
        run_id, queued_prompt_input(text), thread.workspace_id
    )
    response = QueuedPromptResponse.from_record(updated)
    if response is None:
        raise DomainError("Could not project queued prompt")
    return response


@router.post("/queue/{run_id}/edit", status_code=204)
async def begin_prompt_queue_edit(
    thread_id: str,
    run_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> None:
    await runs.begin_queue_edit(thread_id, run_id, thread.workspace_id)


@router.delete("/queue/{run_id}/edit", status_code=204)
async def end_prompt_queue_edit(
    thread_id: str,
    run_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> None:
    await runs.end_queue_edit(thread_id, run_id, thread.workspace_id)


@router.put("/queue/order")
async def reorder_prompt_queue(
    thread_id: str,
    body: QueuedPromptOrder,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> list[QueuedPromptResponse]:
    records = await runs.reorder_queued_prompts(
        thread_id, body.ordered_ids, thread.workspace_id
    )
    return _queued_responses(records)


@router.delete("/queue/{run_id}", status_code=204)
async def remove_prompt_queue_item(
    thread_id: str,
    run_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> None:
    record = await runs.get(run_id, thread.workspace_id)
    _ensure_run_on_thread(record, thread_id)
    await runs.remove_queued_prompt(run_id)


@router.get("/{run_id}")
async def read_run(
    thread_id: str,
    run_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> RunResponse:
    record = await runs.get(run_id, thread.workspace_id)
    _ensure_run_on_thread(record, thread_id)
    return RunResponse.from_record(record)


@router.post("/{run_id}/cancel")
async def cancel_run(
    thread_id: str,
    run_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> RunResponse:
    record = await runs.get(run_id, thread.workspace_id)
    _ensure_run_on_thread(record, thread_id)
    return RunResponse.from_record(await runs.cancel(run_id))
