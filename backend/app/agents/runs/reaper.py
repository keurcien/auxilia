"""RunReaper — recovers runs orphaned by a worker or instance that died.

Runs periodically (started in `lifespan` alongside the dispatcher). It scans the
active set rather than `SCAN run:*` so it never trips over the :events/:control
sub-keys. Finalizing through `RunService` means a reaped run still emits the
`end` sentinel, so any client subscribed to it stops cleanly.
"""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus


logger = logging.getLogger(__name__)


class RunReaper:
    def __init__(self, redis=None):
        self.service = RunService(redis)
        self.registry = self.service.registry
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        logger.info(
            "run reaper started: interval=%ss", run_settings.reaper_interval_seconds
        )
        while not self._stopping.is_set():
            try:
                await self._sweep()
            except Exception:  # noqa: BLE001 — a bad sweep must not kill the loop
                logger.exception("Reaper sweep failed")
            await self._sleep(run_settings.reaper_interval_seconds)

    async def _sweep(self) -> None:
        now = datetime.now(UTC)
        for run_id in await self.registry.list_active_ids():
            record = await self.registry.get(run_id)
            if record is None:
                await self.registry.discard_active_id(run_id)
                continue
            if record.status == RunStatus.running:
                last = record.last_heartbeat or record.updated_at
                if (
                    now - last
                ).total_seconds() > run_settings.heartbeat_timeout_seconds:
                    logger.warning("Reaping stale running run %s", run_id)
                    await self.service.finalize(
                        run_id, RunStatus.error, error="Worker stopped responding."
                    )
            elif record.status == RunStatus.pending:
                if (
                    now - record.created_at
                ).total_seconds() > run_settings.pending_timeout_seconds:
                    logger.warning("Reaping stuck pending run %s", run_id)
                    await self.service.finalize(
                        run_id, RunStatus.error, error="Run was never dispatched."
                    )

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake early if asked to stop."""
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)

    def stop(self) -> None:
        self._stopping.set()
