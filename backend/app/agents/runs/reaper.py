"""RunReaper — recovers runs orphaned by a worker or instance that died.

Runs periodically (started in `lifespan` alongside the dispatcher). The
worklist comes from Postgres (`running` / stale `pending` rows); death is
detected via the Redis liveness key. Finalizing through `RunService` means a
reaped run still emits the `end` sentinel (so any subscriber stops cleanly)
and still stamps `threads.last_run_status`. It also owns the daily retention
prune of terminal run rows.
"""

import logging
import time
from datetime import UTC, datetime, timedelta

from app.agents.runs.liveness import DispatcherLiveness, RunLiveness
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus
from app.background import PeriodicLoop


logger = logging.getLogger(__name__)

_PRUNE_INTERVAL_SECONDS = 24 * 3600


class RunReaper:
    def __init__(self, redis=None):
        self.service = RunService(redis)
        self.dispatchers = DispatcherLiveness(self.service.redis)
        self._last_prune: float | None = None
        # Run ids that looked dead on the previous sweep — see `_reap_dead_running`.
        self._suspect: set[str] = set()
        self._loop = PeriodicLoop(
            "run-reaper", run_settings.reaper_interval_seconds, self._sweep
        )

    async def run(self) -> None:
        logger.info("run reaper retention=%sd", run_settings.retention_days)
        await self._loop.run()

    async def _sweep(self) -> None:
        now = datetime.now(UTC)
        await self._reap_dead_running(now)
        await self._reap_undispatched_pending(now)
        await self._maybe_prune(now)

    async def _reap_dead_running(self, now: datetime) -> None:
        """Finalize `running` runs whose worker is gone.

        The updated_at grace window covers the claim → first-stamp gap (and any
        Redis hiccup shorter than the heartbeat timeout).

        Death then has to be observed **twice in a row**. The liveness key is
        the only evidence, and a Redis restart makes every key missing at once —
        a single-sample rule would mass-reap a whole cluster of healthy
        streaming runs. Confirming costs one reaper interval of extra latency on
        a genuinely dead run and removes that failure mode entirely.
        """
        grace = timedelta(seconds=run_settings.heartbeat_timeout_seconds)
        suspect_now: set[str] = set()
        for record in await self.service.list_running():
            if await RunLiveness(record.id, self.service.redis).is_alive():
                continue
            if now - record.updated_at < grace:
                continue
            suspect_now.add(record.id)
            if record.id not in self._suspect:
                logger.info(
                    "Run %s looks dead; waiting for a second sweep to confirm",
                    record.id,
                )
                continue
            logger.warning("Reaping stale running run %s", record.id)
            await self.service.finalize(
                record.id, RunStatus.error, error="Worker stopped responding."
            )
        self._suspect = suspect_now

    async def _reap_undispatched_pending(self, now: datetime) -> None:
        """Finalize `pending` runs that will never be picked up.

        Only when **no dispatcher in the cluster is alive**. "Pending past the
        dispatch timeout with an idle thread" is equally the state of every run
        legitimately queued behind a saturated worker pool — a burst of trigger
        firings, each on its own fresh thread, produces exactly that shape and
        used to get healthy runs killed mid-queue. A live dispatcher means the
        backlog is being worked through; the absence of one is what makes a
        pending run a zombie. (A pending run behind a *running* one is a
        legitimate `enqueue` waiter and is skipped by the query itself.)

        Trade-off, on purpose: a dispatcher that is alive but wedged leaves
        pending runs un-reaped. That is a supervision problem (P1-12), and
        failing to reap is far cheaper than killing runs that were about to run.
        """
        if await self.dispatchers.any_alive():
            return
        cutoff = now - timedelta(seconds=run_settings.pending_timeout_seconds)
        for record in await self.service.list_stuck_pending(cutoff):
            logger.warning("Reaping stuck pending run %s", record.id)
            # expected=pending: if a dispatcher claimed it between the list
            # and this call, the guarded update is a no-op instead of marking
            # a now-running run "never dispatched".
            await self.service.finalize(
                record.id,
                RunStatus.error,
                error="Run was never dispatched.",
                expected=RunStatus.pending,
            )

    async def _maybe_prune(self, now: datetime) -> None:
        """Daily retention pass: drop terminal run rows past `retention_days`.
        Safe anytime — `threads.last_run_status` is denormalized, so pruning
        never breaks the thread badge."""
        if (
            self._last_prune is not None
            and time.monotonic() - self._last_prune < _PRUNE_INTERVAL_SECONDS
        ):
            return
        cutoff = now - timedelta(days=run_settings.retention_days)
        pruned = await self.service.prune_terminal(cutoff)
        # Stamped only after the delete succeeds, so a transient failure is
        # retried on the next sweep instead of waiting out a full day.
        self._last_prune = time.monotonic()
        if pruned:
            logger.info("Pruned %s terminal runs older than %s", pruned, cutoff)

    def stop(self) -> None:
        self._loop.stop()
