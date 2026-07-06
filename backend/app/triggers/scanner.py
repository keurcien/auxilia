"""TriggerScanner — the periodic due-trigger loop.

A sibling of `RunReaper` (same lifecycle, started in `lifespan` on always-on
worker instances). Each tick opens its own session — the out-of-request
pattern — and delegates to `TriggerService.claim_and_enqueue`, which owns the
claim/commit/enqueue choreography. `FOR UPDATE SKIP LOCKED` in the claim query
makes it safe to run the scanner on every instance; no leader election.
"""

import asyncio
import logging
from contextlib import suppress

from app.database import AsyncSessionLocal
from app.triggers.service import TriggerService
from app.triggers.settings import trigger_settings


logger = logging.getLogger(__name__)


class TriggerScanner:
    def __init__(self):
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        logger.info(
            "trigger scanner started: interval=%ss",
            trigger_settings.scan_interval_seconds,
        )
        while not self._stopping.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 — a bad tick must not kill the loop
                logger.exception("Trigger scan failed")
            await self._sleep(trigger_settings.scan_interval_seconds)

    async def _tick(self) -> None:
        async with AsyncSessionLocal() as db:
            run_ids = await TriggerService(db).claim_and_enqueue()
        if run_ids:
            logger.info("Enqueued %d triggered run(s)", len(run_ids))

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake early if asked to stop."""
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)

    def stop(self) -> None:
        self._stopping.set()
