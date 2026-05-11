"""Domain operations for runs.

The router only ever talks to this module. Anything that needs to coordinate
the registry, queue, and event stream lives here so the layered shape stays
honest (PRD §5.5).

State is Redis-only. We used to mirror every run into a Postgres ``runs``
audit table, but in practice every column was either covered by Langfuse
(cost / token usage), the LangGraph checkpoint (conversation state), or the
Redis hash itself (live status, error, interrupt). The audit table was
synchronised but never read by any production path, so it was deleted along
with its migration in commit history. If long-term run telemetry becomes a
real need, pipe it through Langfuse metadata rather than reviving the table.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runs.control import RunControl
from app.agents.runs.events import RunEvents
from app.agents.runs.queue import RunQueue
from app.agents.runs.registry import RunRegistry
from app.agents.runs.schemas import RunCreate, RunResponse
from app.agents.runs.state import (
    CancellationReason,
    MultitaskStrategy,
    RunRecord,
    RunState,
    is_active,
    is_terminal,
    utcnow,
)
from app.agents.runs.worker import store_input
from app.database import get_db
from app.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.threads.service import ThreadService
from app.users.models import UserDB


logger = logging.getLogger(__name__)


class RunConflictError(AlreadyExistsError):
    """Another run is already active on this thread and the strategy is reject."""


class RunService:
    """Live run operations. Backed entirely by Redis.

    Takes ``db`` because thread permission checks go through ``ThreadService``;
    it is not used to persist any run state of its own.
    """

    not_found_message = "Run not found"

    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis
        self.registry = RunRegistry(redis)
        self.events = RunEvents(redis)
        self.control = RunControl(redis)
        self.queue = RunQueue(redis)

    # ---- create ----

    async def create_run(
        self,
        thread_id: str,
        current_user: UserDB,
        body: RunCreate,
    ) -> RunRecord:
        """Apply ``multitask_strategy``, persist a Redis record, enqueue."""
        thread = await ThreadService(self.db).get_thread(thread_id)
        if thread.user_id != current_user.id:
            raise PermissionDeniedError("You do not have access to this thread")

        await self._apply_multitask_strategy(thread_id, body.multitask_strategy)

        run_id = uuid4()
        now = utcnow()
        record = RunRecord(
            id=run_id,
            thread_id=thread_id,
            user_id=current_user.id,
            agent_id=thread.agent_id,
            status=RunState.PENDING,
            multitask_strategy=body.multitask_strategy,
            created_at=now,
            updated_at=now,
            input_summary=_summarise_input(body),
            model_id=thread.model_id,
        )

        await self.registry.create(record)
        # Best-effort active-run pointer. If another run set it first, the
        # multitask_strategy step above would have caught it; in race conditions
        # we accept the existing value.
        await self.registry.try_set_active(thread_id, run_id)

        # Stash the body so the worker can resurrect input/command/config.
        await store_input(
            self.redis,
            run_id,
            {
                "input": body.input,
                "command": body.command,
                "config_overrides": _extract_config_overrides(body.config),
                "trigger": _extract_trigger(body.config),
            },
        )

        await self.queue.enqueue(run_id)
        logger.info(
            "created run %s on thread %s (strategy=%s) — enqueued",
            run_id,
            thread_id,
            body.multitask_strategy.value,
        )
        return record

    async def _apply_multitask_strategy(
        self,
        thread_id: str,
        strategy: MultitaskStrategy,
    ) -> None:
        active_id = await self.registry.get_active(thread_id)
        if active_id is None:
            return
        active = await self.registry.get(active_id)
        if active is None or not is_active(active.status):
            await self.registry.clear_active_if_match(thread_id, active_id)
            return

        if strategy is MultitaskStrategy.REJECT:
            raise RunConflictError(
                f"Thread already has an active run {active_id}. Reattach or cancel first."
            )
        if strategy is MultitaskStrategy.INTERRUPT:
            await self.control.signal_cancel(active_id, CancellationReason.REPLACED)
            await self.registry.clear_active_if_match(thread_id, active_id)
            return
        if strategy is MultitaskStrategy.ENQUEUE:
            # Workers process the queue FIFO; the new run will start when the
            # current one releases the active-run pointer on terminal state.
            return
        if strategy is MultitaskStrategy.ROLLBACK:
            raise ValidationError(
                "multitask_strategy=rollback is not yet implemented"
            )

    # ---- get / list ----

    async def get_run(self, run_id: UUID, current_user: UserDB) -> RunRecord:
        record = await self.registry.get(run_id)
        if record is None:
            # Redis TTL is 24h — runs older than that are gone. If you need
            # long-term run history, route telemetry through Langfuse.
            raise NotFoundError(self.not_found_message)
        if record.user_id != current_user.id:
            raise PermissionDeniedError("You do not have access to this run")
        return record

    async def list_runs(
        self, thread_id: str, current_user: UserDB
    ) -> list[RunResponse]:
        thread = await ThreadService(self.db).get_thread(thread_id)
        if thread.user_id != current_user.id:
            raise PermissionDeniedError("You do not have access to this thread")
        records = await self.registry.list_by_thread(thread_id)
        return [record_to_response(r) for r in records]

    async def get_active_run(
        self, thread_id: str, current_user: UserDB
    ) -> RunRecord | None:
        thread = await ThreadService(self.db).get_thread(thread_id)
        if thread.user_id != current_user.id:
            raise PermissionDeniedError("You do not have access to this thread")
        active_id = await self.registry.get_active(thread_id)
        if active_id is None:
            return None
        record = await self.registry.get(active_id)
        return record if record and is_active(record.status) else None

    # ---- cancel ----

    async def cancel_run(
        self,
        run_id: UUID,
        current_user: UserDB,
        *,
        reason: CancellationReason = CancellationReason.USER,
    ) -> RunRecord:
        record = await self.get_run(run_id, current_user)
        if is_terminal(record.status):
            return record  # idempotent
        await self.control.signal_cancel(record.id, reason)
        return record

    # ---- stream ----

    async def stream_events(
        self,
        run_id: UUID,
        current_user: UserDB,
        *,
        last_event_id: str = "0",
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        await self.get_run(run_id, current_user)  # auth check
        async for stream_id, event in self.events.read(
            run_id, last_id=last_event_id
        ):
            yield stream_id, event
            if event.get("type") == "end":
                return


# --- helpers ----------------------------------------------------------------


def _summarise_input(body: RunCreate) -> dict[str, Any]:
    """Cheap, bounded summary of the POST body for debugging.

    Never store the full raw payload here — that goes into ``run:{rid}:input``.
    The summary lives in Redis ``run:{rid}`` and gets surfaced by the runs API.
    """
    if body.command is not None:
        return {"kind": "resume", "has_decisions": "decisions" in (body.command or {})}
    msgs = (body.input or {}).get("messages", []) if body.input else []
    text_preview: str | None = None
    file_count = 0
    if msgs:
        first = msgs[0]
        content = first.get("content") if isinstance(first, dict) else None
        if isinstance(content, str):
            text_preview = content[:200]
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and text_preview is None:
                        text_preview = (block.get("text") or "")[:200]
                    elif block.get("type") in {"file", "image_url"}:
                        file_count += 1
    return {
        "kind": "input",
        "text_preview": text_preview,
        "file_count": file_count,
    }


def _extract_trigger(config: dict[str, Any] | None) -> str | None:
    if not config:
        return None
    configurable = config.get("configurable") or {}
    return configurable.get("trigger")


def _extract_config_overrides(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not config:
        return None
    configurable = dict(config.get("configurable") or {})
    configurable.pop("trigger", None)
    configurable.pop("thread_id", None)
    if not configurable:
        return None
    return {**config, "configurable": configurable}


def record_to_response(record: RunRecord) -> RunResponse:
    return RunResponse(
        run_id=record.id,
        thread_id=record.thread_id,
        agent_id=record.agent_id,
        status=record.status,
        multitask_strategy=record.multitask_strategy,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        cancellation_reason=record.cancellation_reason,
        error=record.error,
        interrupt=record.interrupt,
        model_id=record.model_id,
    )


# --- DI ---------------------------------------------------------------------


def get_redis(request: Request) -> Redis:
    """FastAPI dependency exposing the lifespan-owned Redis client."""
    return request.app.state.redis


def get_run_service(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RunService:
    return RunService(db, redis)
