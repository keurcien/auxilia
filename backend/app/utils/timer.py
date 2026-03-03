import logging
import time
from contextlib import asynccontextmanager, contextmanager

logger = logging.getLogger(__name__)


class RequestTimer:
    """Lightweight span-based timer for profiling the invoke endpoint.

    Usage::

        timer = RequestTimer("invoke", enabled=True)

        async with timer.aspan("read_agent"):
            ...

        with timer.span("message_processing"):
            ...

        timer.summary()  # emits a DEBUG log with all spans and percentages
    """

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled
        self._spans: list[tuple[str, float]] = []
        self._start = time.perf_counter()

    def _offset_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000

    @contextmanager
    def span(self, label: str):
        if not self.enabled:
            yield
            return
        t0 = time.perf_counter()
        logger.debug("[%s] → %s  (T+%.1fms)", self.name, label, self._offset_ms())
        try:
            yield
        finally:
            elapsed = time.perf_counter() - t0
            self._spans.append((label, elapsed))
            logger.debug("[%s] ← %s: %.1fms  (T+%.1fms)", self.name, label, elapsed * 1000, self._offset_ms())

    @asynccontextmanager
    async def aspan(self, label: str):
        if not self.enabled:
            yield
            return
        t0 = time.perf_counter()
        logger.debug("[%s] → %s  (T+%.1fms)", self.name, label, self._offset_ms())
        try:
            yield
        finally:
            elapsed = time.perf_counter() - t0
            self._spans.append((label, elapsed))
            logger.debug("[%s] ← %s: %.1fms  (T+%.1fms)", self.name, label, elapsed * 1000, self._offset_ms())

    def record(self, label: str, elapsed: float) -> None:
        """Record a pre-measured span (e.g. time-to-first-chunk)."""
        if not self.enabled:
            return
        self._spans.append((label, elapsed))
        logger.debug("[%s] %s: %.1fms  (T+%.1fms)", self.name, label, elapsed * 1000, self._offset_ms())

    def summary(self) -> None:
        if not self.enabled or not self._spans:
            return
        total = time.perf_counter() - self._start
        lines = [f"\n[{self.name}] TOTAL: {total * 1000:.1f}ms"]
        for label, elapsed in self._spans:
            pct = (elapsed / total * 100) if total > 0 else 0
            lines.append(f"  {label:.<40} {elapsed * 1000:>8.1f}ms  ({pct:4.1f}%)")
        logger.debug("\n".join(lines))
