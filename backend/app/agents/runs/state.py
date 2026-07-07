"""What a run *is*: its lifecycle and the legal transitions.

A run is the execution envelope around one agent turn (see `SPEC.md`). Its
record is the `RunDB` row in Postgres (`models.py`); durable conversation
state stays in the LangGraph checkpoint.
"""

from enum import Enum


class RunStatus(str, Enum):
    """Run lifecycle. Names match the LangGraph Server v1 wire shape; `cancelled`
    is auxilia's explicit Stop."""

    pending = "pending"
    running = "running"
    interrupted = "interrupted"
    success = "success"
    error = "error"
    timeout = "timeout"
    cancelled = "cancelled"


# Terminal states stamp `threads.last_run_status` and TTL the run's Redis
# ephemera. `interrupted` is terminal *for this run* — resuming a HITL
# interrupt creates a new run.
TERMINAL_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.interrupted,
        RunStatus.success,
        RunStatus.error,
        RunStatus.timeout,
        RunStatus.cancelled,
    }
)

# Exhaustive transition table. Anything not listed is illegal and raises.
# The repository enforces this shape in SQL (claim: WHERE status='pending';
# finalize: WHERE status NOT IN terminal) — this table stays the readable
# spec and the guard for any in-Python transition.
_ALLOWED: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.pending: frozenset(
        {RunStatus.running, RunStatus.cancelled, RunStatus.error}
    ),
    RunStatus.running: frozenset(
        {
            RunStatus.interrupted,
            RunStatus.success,
            RunStatus.error,
            RunStatus.timeout,
            RunStatus.cancelled,
        }
    ),
    RunStatus.interrupted: frozenset(),
    RunStatus.success: frozenset(),
    RunStatus.error: frozenset(),
    RunStatus.timeout: frozenset(),
    RunStatus.cancelled: frozenset(),
}


class InvalidRunTransitionError(Exception):
    """Raised on an illegal status transition — always a programming bug."""

    def __init__(self, current: RunStatus, target: RunStatus):
        super().__init__(f"Illegal run transition: {current.value} → {target.value}")
        self.current = current
        self.target = target


def transition(current: RunStatus, target: RunStatus) -> RunStatus:
    """Return `target` if `current → target` is legal, else raise."""
    if target not in _ALLOWED[current]:
        raise InvalidRunTransitionError(current, target)
    return target


def is_terminal(status: RunStatus) -> bool:
    return status in TERMINAL_STATUSES
