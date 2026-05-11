"""Run state machine.

Single source of truth for what states a run can be in and how it transitions.
Every state mutation in the runtime goes through ``transition()``.

State names match the LangGraph Server v1 vocabulary (``pending`` / ``running``
/ ``interrupted`` / ``success`` / ``error`` / ``timeout``) plus auxilia's
explicit ``cancelled`` for user/system-initiated stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID


class RunState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class RunEvent(str, Enum):
    """State machine inputs. Anything that can change a run's status."""

    DEQUEUED = "dequeued"
    INTERRUPT_EMITTED = "interrupt_emitted"
    COMPLETED = "completed"
    ERRORED = "errored"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class CancellationReason(str, Enum):
    USER = "user"
    REPLACED = "replaced"
    TIMEOUT = "timeout"
    SYSTEM = "system"


class MultitaskStrategy(str, Enum):
    """LangGraph-Server-compatible policy for handling concurrent runs on a thread.

    - ``reject`` — refuse the new run (HTTP 409). Frontend may reattach.
    - ``enqueue`` — queue the new run after the current one finishes.
    - ``interrupt`` — cancel the current run, then start the new one.
    - ``rollback`` — cancel current and rewind the checkpoint to before it ran.
    """

    REJECT = "reject"
    ENQUEUE = "enqueue"
    INTERRUPT = "interrupt"
    ROLLBACK = "rollback"


TERMINAL_STATES: frozenset[RunState] = frozenset(
    {RunState.SUCCESS, RunState.ERROR, RunState.CANCELLED, RunState.TIMEOUT}
)
ACTIVE_STATES: frozenset[RunState] = frozenset(
    {RunState.PENDING, RunState.RUNNING, RunState.INTERRUPTED}
)


_TRANSITIONS: dict[tuple[RunState, RunEvent], RunState] = {
    (RunState.PENDING, RunEvent.DEQUEUED): RunState.RUNNING,
    (RunState.PENDING, RunEvent.CANCELLED): RunState.CANCELLED,
    (RunState.PENDING, RunEvent.ERRORED): RunState.ERROR,
    (RunState.RUNNING, RunEvent.INTERRUPT_EMITTED): RunState.INTERRUPTED,
    (RunState.RUNNING, RunEvent.COMPLETED): RunState.SUCCESS,
    (RunState.RUNNING, RunEvent.ERRORED): RunState.ERROR,
    (RunState.RUNNING, RunEvent.CANCELLED): RunState.CANCELLED,
    (RunState.RUNNING, RunEvent.TIMED_OUT): RunState.TIMEOUT,
    (RunState.INTERRUPTED, RunEvent.CANCELLED): RunState.CANCELLED,
    (RunState.INTERRUPTED, RunEvent.ERRORED): RunState.ERROR,
}


class IllegalTransitionError(Exception):
    def __init__(self, current: RunState, event: RunEvent):
        super().__init__(
            f"Illegal run state transition: {current.value} --[{event.value}]--> ?"
        )
        self.current = current
        self.event = event


def transition(current: RunState, event: RunEvent) -> RunState:
    """Apply ``event`` to a run currently in ``current``, returning the new state.

    Raises ``IllegalTransitionError`` if the transition is not in the table. The
    caller is expected to either know the run is in a legal source state, or to
    catch the exception and translate to a domain error (e.g. cancelling a run
    that has already terminated).
    """
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError:
        raise IllegalTransitionError(current, event) from None


def is_terminal(state: RunState) -> bool:
    return state in TERMINAL_STATES


def is_active(state: RunState) -> bool:
    return state in ACTIVE_STATES


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Live run state, mirrored to Redis hash ``run:{id}``.

    Frozen on purpose: every mutation produces a new instance via
    ``dataclasses.replace`` and is written through the registry. This makes the
    Redis writes the only place where state can change, and gives us cheap
    equality for tests.
    """

    id: UUID
    thread_id: str
    user_id: UUID
    agent_id: UUID
    status: RunState
    multitask_strategy: MultitaskStrategy
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    worker_id: str | None = None
    last_event_id: str | None = None
    interrupt: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cancellation_reason: CancellationReason | None = None
    input_summary: dict[str, Any] | None = None
    model_id: str | None = None
