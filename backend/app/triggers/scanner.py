"""TriggerScanner — the periodic due-trigger loop.

A sibling of `RunReaper` (same lifecycle, started in `lifespan` on always-on
worker instances). Each tick opens its own session — the out-of-request
pattern — and delegates to `TriggerService.claim_and_enqueue`, which owns the
claim/commit/enqueue choreography. `FOR UPDATE SKIP LOCKED` in the claim query
makes it safe to run the scanner on every instance; no leader election.
"""

import logging

from app.background import PeriodicLoop
from app.database import AsyncSessionLocal
from app.triggers.service import TriggerService
from app.triggers.settings import trigger_settings


logger = logging.getLogger(__name__)


class TriggerScanner:
    def __init__(self):
        self._loop = PeriodicLoop(
            "trigger-scanner", trigger_settings.scan_interval_seconds, self._tick
        )

    async def run(self) -> None:
        await self._loop.run()

    async def _tick(self) -> None:
        async with AsyncSessionLocal() as db:
            run_ids = await TriggerService(db).claim_and_enqueue()
        if run_ids:
            logger.info("Enqueued %d triggered run(s)", len(run_ids))

    def stop(self) -> None:
        self._loop.stop()
