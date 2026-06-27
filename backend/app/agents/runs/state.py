"""What a run *is*: its lifecycle, its record, and the legal transitions.

A run is the execution envelope around one agent turn (see `SPEC.md`). It lives
in Redis only — durable conversation state stays in the LangGraph checkpoint.
"""

import json
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


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


# Terminal states release the per-thread mutex and get a TTL. `interrupted` is
# terminal *for this run* — resuming a HITL interrupt creates a new run.
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


def _now() -> datetime:
    return datetime.now(UTC)


class RunRecord(BaseModel):
    """The operational state of a run, serialized into a Redis hash.

    `input`/`command`/`trigger`/`config_overrides` are the parameters the worker
    replays into `Agent.stream(...)`. Conversation state is *not* here — it lives
    in the thread's LangGraph checkpoint.
    """

    id: str
    thread_id: str
    user_id: str
    status: RunStatus = RunStatus.pending
    multitask_strategy: str = "reject"

    # Run parameters (mutually: input for a new turn, command for a HITL resume).
    input: dict | None = None
    command: dict | None = None
    trigger: str | None = None
    config_overrides: dict | None = None

    # Terminal error text, when status is `error`/`timeout`.
    error: str | None = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    last_heartbeat: datetime | None = None

    def to_redis(self) -> dict[str, str]:
        """Serialize to a flat str→str mapping for HSET. Each field is JSON so
        reads round-trip uniformly; `None` fields are omitted."""
        return {
            key: json.dumps(value)
            for key, value in self.model_dump(mode="json").items()
            if value is not None
        }

    @classmethod
    def from_redis(cls, raw: dict[str, str]) -> "RunRecord":
        """Rebuild from a HGETALL mapping written by `to_redis`."""
        return cls(**{key: json.loads(value) for key, value in raw.items()})
