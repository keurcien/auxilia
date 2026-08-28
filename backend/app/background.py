"""Supervised background loops, and a registry so `/health` can see them.

The failure this exists to prevent: a background loop dies, logs one ERROR, and
the instance carries on answering 200s while nothing executes runs or fires
triggers ever again (design review §2.3). On Cloud Run that instance also keeps
passing its health check, so nothing recycles it — the deployment is broken and
looks fine.

Two halves, and both are needed:

* **Supervision** — a raising tick is logged and retried with exponential
  backoff, so a transient failure (Postgres failing over, Redis blipping) costs
  a retry rather than the loop. `TriggerScanner` and `RunReaper` already caught
  per-tick exceptions; what they lacked was backoff, so a persistent failure
  became a tight error-logging spin.
* **Reporting** — supervision cannot save a loop from a bug in the supervisor,
  a cancellation, or a `BaseException`. Liveness is therefore published, not
  assumed, and `/health` fails the instance when a loop has stopped ticking.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)

# Backoff after a failing tick: doubles from the loop's own interval up to this.
MAX_BACKOFF_SECONDS = 60.0


@dataclass
class LoopHealth:
    """What a loop publishes about itself.

    `last_tick_at` is `time.monotonic()`, not a wall clock: it is only ever read
    as an age, and a wall clock can jump.
    """

    name: str
    interval: float
    started: bool = False
    stopped: bool = False
    last_tick_at: float | None = None
    consecutive_failures: int = 0
    last_error: str | None = None

    def mark_tick(self) -> None:
        self.last_tick_at = time.monotonic()
        self.consecutive_failures = 0
        self.last_error = None

    def mark_failure(self, exc: BaseException) -> None:
        self.consecutive_failures += 1
        self.last_error = repr(exc)

    @property
    def seconds_since_tick(self) -> float | None:
        if self.last_tick_at is None:
            return None
        return time.monotonic() - self.last_tick_at

    def is_healthy(self, *, tolerance: float = 3.0) -> bool:
        """Healthy while it is ticking roughly on schedule.

        A loop that has been asked to stop is healthy — that is shutdown, not
        failure. One that has started but never ticked is judged on the same
        deadline as a running one, so a loop that dies on its very first tick is
        still caught.
        """
        if self.stopped or not self.started:
            return True
        deadline = self.interval * tolerance + MAX_BACKOFF_SECONDS
        age = self.seconds_since_tick
        return age is not None and age <= deadline

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "healthy": self.is_healthy(),
            "started": self.started,
            "stopped": self.stopped,
            "seconds_since_tick": (
                None
                if self.seconds_since_tick is None
                else round(self.seconds_since_tick, 1)
            ),
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
        }


@dataclass
class LoopRegistry:
    """Every background loop this process is supposed to be running."""

    loops: list[LoopHealth] = field(default_factory=list)

    def register(self, health: LoopHealth) -> LoopHealth:
        self.loops.append(health)
        return health

    def clear(self) -> None:
        self.loops.clear()

    @property
    def healthy(self) -> bool:
        return all(loop.is_healthy() for loop in self.loops)

    def snapshot(self) -> list[dict]:
        return [loop.snapshot() for loop in self.loops]


registry = LoopRegistry()


class PeriodicLoop:
    """Runs `tick` every `interval` seconds until stopped, surviving failures.

    Deliberately not a base class: the two loops that fit this shape (the reaper
    and the trigger scanner) keep owning their own tick, and `RunDispatcher` —
    which is not periodic at all, it blocks on a semaphore — reuses `LoopHealth`
    without pretending to be one.
    """

    def __init__(
        self,
        name: str,
        interval: float,
        tick: Callable[[], Awaitable[None]],
    ):
        self.health = registry.register(LoopHealth(name=name, interval=interval))
        self._name = name
        self._interval = interval
        self._tick = tick
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        logger.info("%s started: interval=%ss", self._name, self._interval)
        self.health.started = True
        self.health.mark_tick()  # not yet stale at t=0
        backoff = self._interval
        while not self._stopping.is_set():
            try:
                await self._tick()
            except Exception as exc:
                self.health.mark_failure(exc)
                logger.exception(
                    "%s tick failed (%s consecutive); retrying in %.1fs",
                    self._name,
                    self.health.consecutive_failures,
                    backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue
            self.health.mark_tick()
            backoff = self._interval
            await self._sleep(self._interval)
        self.health.stopped = True

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake early if asked to stop."""
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)

    def stop(self) -> None:
        self._stopping.set()
        self.health.stopped = True
