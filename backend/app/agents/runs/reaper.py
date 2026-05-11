"""Periodic orphan detection.

Runs every ``REAPER_INTERVAL_SECONDS``. Looks for runs whose worker has not
written a heartbeat in ``HEARTBEAT_TIMEOUT_SECONDS``. For each:

- Patches dangling tool calls so the thread is consistent for the user.
- Transitions the run to ``error`` with reason ``system``.
- Releases the per-thread ``active_run`` mutex.
- Emits an ``end`` event so any still-attached SSE consumers unblock.

This is the *only* thing that recovers a run after the worker process dies
mid-stream (Cloud Run instance termination, OOM, SIGKILL). Without it,
``thread:{tid}:active_run`` would block all subsequent runs on the thread
until the TTL expires.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.agents.runs.events import RunEvents
from app.agents.runs.patch import patch_dangling_tool_calls
from app.agents.runs.registry import RunRegistry
from app.agents.runs.state import (
    IllegalTransitionError,
    RunEvent,
    RunRecord,
    RunState,
    transition,
    utcnow,
)
from app.database import get_psycopg_conn_string


logger = logging.getLogger(__name__)


REAPER_INTERVAL_SECONDS: float = 30.0
# Max time a RUNNING worker can go without writing a heartbeat before we treat
# it as dead. Workers heartbeat every 5s (HEARTBEAT_INTERVAL_SECONDS in
# worker.py), so 30s is a generous 6x margin.
HEARTBEAT_TIMEOUT_SECONDS: float = 30.0
# A PENDING run is just queued — if every worker is busy on a previous run,
# it sits here legitimately. Only reap PENDING after a *much* longer threshold
# so a single slow run on a single-worker deploy doesn't poison the queue.
PENDING_TIMEOUT_SECONDS: float = 10 * 60.0


class RunReaper:
    def __init__(self, redis):
        self.redis = redis
        self.registry = RunRegistry(redis)
        self.events = RunEvents(redis)

    async def run_forever(self, *, stop_event: asyncio.Event) -> None:
        logger.info("RunReaper starting")
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=REAPER_INTERVAL_SECONDS
                )
            except TimeoutError:
                pass  # tick
            else:
                break  # stop signal arrived
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 — never crash the loop
                logger.exception("reaper tick failed")
        logger.info("RunReaper stopped")

    async def tick(self) -> int:
        """One reaping pass. Returns the number of runs reaped.

        Each active state has its own staleness rule:

        - ``RUNNING``: must heartbeat within ``HEARTBEAT_TIMEOUT_SECONDS``;
          otherwise the worker is presumed dead.
        - ``PENDING``: queued, waiting for a worker. Only reaped after
          ``PENDING_TIMEOUT_SECONDS`` so a single slow run on a single-worker
          deploy doesn't kill everything behind it.
        - ``INTERRUPTED``: paused on a human-in-the-loop interrupt. No
          heartbeat expected; never reaped here. Cleared by the active-run
          TTL on the thread mutex (30 min) if no resume ever lands.
        """
        records = await self.registry.scan_active()
        now = utcnow()
        running_threshold = timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
        pending_threshold = timedelta(seconds=PENDING_TIMEOUT_SECONDS)
        reaped = 0
        for record in records:
            if record.status == RunState.INTERRUPTED:
                continue
            if record.status == RunState.PENDING:
                age = now - record.created_at if record.created_at else None
                if age is None or age <= pending_threshold:
                    continue
            elif record.status == RunState.RUNNING:
                # Heartbeat is the only signal we trust here. ``started_at`` is
                # set when the worker dequeues; if heartbeat is missing the
                # worker died before the heartbeat loop ran.
                beat = record.heartbeat_at or record.started_at
                if beat is None or now - beat <= running_threshold:
                    continue
            else:
                continue  # other states are terminal — registry filtered them
            try:
                await self._reap(record)
                reaped += 1
            except Exception:  # noqa: BLE001
                logger.exception("failed to reap run %s", record.id)
        return reaped

    async def _reap(self, record: RunRecord) -> None:
        logger.warning(
            "reaping orphaned run %s (status=%s, last beat=%s)",
            record.id,
            record.status,
            record.heartbeat_at,
        )
        # Patch dangling tool calls so the thread is consistent.
        try:
            await self._patch_thread(record)
        except Exception:  # noqa: BLE001
            logger.exception("patch_dangling_tool_calls failed for %s", record.id)

        try:
            new_status = transition(record.status, RunEvent.ERRORED)
        except IllegalTransitionError:
            new_status = RunState.ERROR

        await self.registry.update(
            record.id,
            status=new_status,
            completed_at=utcnow(),
            error={"type": "WorkerOrphaned", "message": "Worker heartbeat lost"},
        )
        await self.events.append(
            record.id,
            {
                "type": "end",
                "status": new_status.value,
                "error": {
                    "type": "WorkerOrphaned",
                    "message": "Worker heartbeat lost",
                },
            },
        )
        await self.events.expire(record.id)
        await self.registry.clear_active_if_match(record.thread_id, record.id)

    async def _patch_thread(self, record: RunRecord) -> None:
        """Rebuild the agent graph for this thread and run the standard patcher.

        Heavier than the worker's path because we have to recreate the
        ``AgentRuntime`` from scratch (no shared in-process state) — but the
        reaper only runs on orphans, which by definition are rare. Using the
        full graph means the synthetic ``ToolMessage`` ends up at the same
        checkpoint level as it would have if the worker hadn't died, instead
        of waiting for the next user turn for ``deepagents`` to patch it.
        """
        from app.agents.runtime import AgentRuntime  # local: avoid import cycle
        from app.database import AsyncSessionLocal
        from app.threads.service import ThreadService

        async with AsyncSessionLocal() as db:
            try:
                thread = await ThreadService(db).get_thread(record.thread_id)
                runtime = await AgentRuntime.build(thread=thread, db=db)
            finally:
                await db.commit()

        async with AsyncPostgresSaver.from_conn_string(
            get_psycopg_conn_string()
        ) as checkpointer:
            graph = runtime._build_agent(checkpointer)
            config = await runtime._resolve_config(
                graph, trigger=None, config_overrides=None
            )
            patched = await patch_dangling_tool_calls(graph, config)
            if patched:
                logger.info(
                    "reaper patched %d dangling tool calls for thread %s",
                    patched,
                    record.thread_id,
                )
