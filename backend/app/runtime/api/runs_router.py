"""HTTP surface for the durable runtime, nested under a thread.

Run CRUD, `/invoke` (create + block for the result), `/stream` (create + relay
that run's events, for external clients), `/cancel`, and the `/runs/active`
poll. A thread's live session is the Agent Streaming Protocol's job:
`POST /threads/{id}/commands` starts runs and `POST /threads/{id}/stream/events`
relays their event log (`app/runtime/api/protocol_router.py`). `/stream` speaks
the same frames: it is one more reader of the log, not a second wire format.
"""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService, get_agent_service
from app.agents.models import EffectivePermission
from app.artifacts.service import ArtifactService, get_artifact_service
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.exceptions import (
    DomainError,
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    StructuredOutputError,
)
from app.redis_client import get_redis
from app.runtime.agent import read_run_result
from app.runtime.api.protocol_service import ProtocolService
from app.runtime.middleware.structured_output import validate_structured_response
from app.runtime.protocol.filter import run_stream_filter
from app.runtime.runs.schemas import (
    QueuedPromptCreate,
    QueuedPromptOrder,
    QueuedPromptPatch,
    QueuedPromptResponse,
    RunCreate,
    RunResponse,
    RunStreamCreate,
    has_queued_prompt_content,
    queued_prompt_content_error,
    queued_prompt_input,
    queued_prompt_input_with_text,
)
from app.runtime.runs.service import RunService
from app.runtime.runs.state import RunStatus
from app.threads.dependencies import authorize_thread_read
from app.threads.models import ThreadDB
from app.threads.schemas import ThreadResponse
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id


router = APIRouter(prefix="/threads/{thread_id}/runs", tags=["runs"])

# User-level surface (not nested under a thread).
user_runs_router = APIRouter(prefix="/runs", tags=["runs"])


SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def get_run_service() -> RunService:
    return RunService(get_redis())


def get_protocol_service() -> ProtocolService:
    return ProtocolService(get_redis())


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
    agents: AgentService = Depends(get_agent_service),
) -> ThreadResponse:
    """Load the thread and require the caller to own it (404 if missing, 403 if not)."""
    thread = await service.get(thread_id)
    if thread.user_id != current_user.id:
        raise PermissionDeniedError("Not authorized to access this thread")
    await agents.require_permission(
        thread.agent_id,
        at_least=EffectivePermission.member,
        action="use this agent",
        user_id=current_user.id,
        user_role=current_user.role,
        user_team_id=current_user.team_id,
        include_archived=True,
    )
    return thread


async def authorize_thread_for_run_service(
    thread: ThreadResponse = Depends(authorize_thread),
    db: AsyncSession = Depends(get_db),
) -> ThreadResponse:
    """Release the auth transaction before RunService opens its own session."""
    await db.commit()
    return thread


async def authorize_thread_read_for_run_service(
    thread: ThreadDB = Depends(authorize_thread_read),
    db: AsyncSession = Depends(get_db),
) -> ThreadDB:
    """Read-only variant: anyone who can open the thread (a viewer of its
    project or trigger, an agent admin) may read its runs and queue."""
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
    # Release the pooled connection before RunService opens its own sessions
    # and before blocking for the whole run. Optional OAuth MCP servers are
    # filtered from the toolset while the worker builds the agent.
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
    result = await read_run_result(thread.workspace_id, thread_id, record.id)
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


@router.post("/stream")
async def stream_run(
    thread_id: str,
    body: RunStreamCreate,
    thread: ThreadResponse = Depends(authorize_thread),
    runs: RunService = Depends(get_run_service),
    protocol: ProtocolService = Depends(get_protocol_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: same session auth used
):
    """Create a run and stream its events until it finishes (SSE).

    `/invoke` for a caller that wants to watch: same body, same durable run,
    but the open connection relays the run's protocol events and closes with
    a `result` frame. Everything that can refuse the run (the model, the
    sandbox, an active run) is decided here, before the stream opens, so it
    still answers with a real status code; past that point the outcome is in
    the `result` frame. Closing the connection does not cancel the run:
    `POST /runs/{run_id}/cancel` does (the id is in `X-Run-Id`).
    """
    # Release the pooled connection before RunService opens its own session
    # (holding both risks pool starvation) and before the response streams
    # for the whole run. Optional OAuth MCP servers are filtered from the
    # toolset while the worker builds the agent, as for /invoke.
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
        output_schema=body.output_schema,
    )
    return StreamingResponse(
        protocol.stream_invoke(
            record,
            run_stream_filter(body.channels, subagents=body.subagents),
            body.output_schema,
        ),
        media_type="text/event-stream",
        headers={**SSE_HEADERS, "X-Run-Id": record.id},
    )


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
    # Release the pooled connection before RunService opens its own session
    # (holding both risks pool starvation), matching /invoke. Optional OAuth
    # MCP servers do not gate run creation.
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
        output_schema=body.output_schema,
    )
    return RunResponse.from_record(record)


@router.get("")
async def list_runs(
    thread_id: str,
    thread: ThreadDB = Depends(authorize_thread_read_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> list[RunResponse]:
    return [
        RunResponse.from_record(r)
        for r in await runs.list_for_thread(thread_id, thread.workspace_id)
    ]


@router.get("/active")
async def get_active_run(
    thread_id: str,
    thread: ThreadDB = Depends(authorize_thread_read_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> RunResponse | None:
    record = await runs.get_active(thread_id, thread.workspace_id)
    return RunResponse.from_record(record) if record else None


@router.post("/retry", status_code=201)
async def retry_failed_run(
    thread_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> RunResponse:
    """Replay the latest failed prompt from its durable run input."""
    record = await runs.retry_latest_failed_input(
        thread_id, thread.workspace_id, thread.user_id
    )
    return RunResponse.from_record(record)


@router.get("/queue")
async def list_prompt_queue(
    thread_id: str,
    thread: ThreadDB = Depends(authorize_thread_read_for_run_service),
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
    artifacts: ArtifactService = Depends(get_artifact_service),
    db: AsyncSession = Depends(get_db),
) -> QueuedPromptResponse:
    content = body.content if body.content is not None else (body.text or "")
    if validation_error := queued_prompt_content_error(content, body.inline_text_files):
        raise DomainValidationError(validation_error)
    if not has_queued_prompt_content(content) and not body.attachment_ids:
        raise DomainValidationError("A queued prompt cannot be empty.")
    attachment_metadata = await artifacts.attachment_metadata(
        thread_id, body.attachment_ids
    )
    await db.commit()
    record = await runs.create(
        thread_id=thread_id,
        user_id=str(thread.user_id),
        input=queued_prompt_input(
            content,
            attachment_metadata,
            display_text=body.display_text,
            inline_text_files=body.inline_text_files,
        ),
        multitask_strategy="enqueue",
        force_queue_position=True,
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
        run_id, queued_prompt_input_with_text(record, text), thread.workspace_id
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


@router.post("/queue/{run_id}/send-now", status_code=204)
async def send_prompt_queue_item_now(
    thread_id: str,
    run_id: str,
    thread: ThreadResponse = Depends(authorize_thread_for_run_service),
    runs: RunService = Depends(get_run_service),
) -> None:
    await runs.send_queued_prompt_now(thread_id, run_id, thread.workspace_id)


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
    thread: ThreadDB = Depends(authorize_thread_read_for_run_service),
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
