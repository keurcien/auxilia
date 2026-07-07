"""RunReaper — recovers runs orphaned by a worker or instance that died.

Runs periodically (started in `lifespan` alongside the dispatcher). The
worklist comes from Postgres (`running` / stale `pending` rows); death is
detected via the Redis liveness key. Finalizing through `RunService` means a
reaped run still emits the `end` sentinel (so any subscriber stops cleanly)
and still stamps `threads.last_run_status`. It also owns the daily retention
prune of terminal run rows.
"""

import asyncio
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from app.agents.runs.liveness import RunLiveness
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus


logger = logging.getLogger(__name__)

_PRUNE_INTERVAL_SECONDS = 24 * 3600


class RunReaper:
    def __init__(self, redis=None):
        self.service = RunService(redis)
        self._stopping = asyncio.Event()
        self._last_prune: float | None = None

    async def run(self) -> None:
        logger.info(
            "run reaper started: interval=%ss retention=%sd",
            run_settings.reaper_interval_seconds,
            run_settings.retention_days,
        )
        while not self._stopping.is_set():
            try:
                await self._sweep()
            except Exception:  # noqa: BLE001 — a bad sweep must not kill the loop
                logger.exception("Reaper sweep failed")
            await self._sleep(run_settings.reaper_interval_seconds)

    async def _sweep(self) -> None:
        now = datetime.now(UTC)
        # Dead workers: a running run whose liveness key is gone. The
        # updated_at grace window covers the claim → first-stamp gap (and any
        # Redis hiccup shorter than the heartbeat timeout).
        grace = timedelta(seconds=run_settings.heartbeat_timeout_seconds)
        for record in await self.service.list_running():
            if await RunLiveness(record.id, self.service.redis).is_alive():
                continue
            if now - record.updated_at < grace:
                continue
            logger.warning("Reaping stale running run %s", record.id)
            await self.service.finalize(
                record.id, RunStatus.error, error="Worker stopped responding."
            )
        # Queued zombies: pending past the dispatch timeout with an idle
        # thread (a pending run behind a running one is a legitimate
        # `enqueue` waiter and is skipped by the query).
        pending_cutoff = now - timedelta(seconds=run_settings.pending_timeout_seconds)
        for record in await self.service.list_stuck_pending(pending_cutoff):
            logger.warning("Reaping stuck pending run %s", record.id)
            await self.service.finalize(
                record.id, RunStatus.error, error="Run was never dispatched."
            )
        await self._maybe_prune(now)

    async def _maybe_prune(self, now: datetime) -> None:
        """Daily retention pass: drop terminal run rows past `retention_days`.
        Safe anytime — `threads.last_run_status` is denormalized, so pruning
        never breaks the thread badge."""
        if (
            self._last_prune is not None
            and time.monotonic() - self._last_prune < _PRUNE_INTERVAL_SECONDS
        ):
            return
        self._last_prune = time.monotonic()
        cutoff = now - timedelta(days=run_settings.retention_days)
        pruned = await self.service.prune_terminal(cutoff)
        if pruned:
            logger.info("Pruned %s terminal runs older than %s", pruned, cutoff)

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake early if asked to stop."""
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)

    def stop(self) -> None:
        self._stopping.set()
