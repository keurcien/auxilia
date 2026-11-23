from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.runtime.protocol.events import KNOWN_CHANNELS
from app.runtime.runs.models import RunDB
from app.runtime.runs.state import MultitaskStrategy, RunStatus


class RunCreate(BaseModel):
    """Client payload for `POST /threads/{thread_id}/runs`.

    `input` starts a new turn; `command` resumes a HITL interrupt. `config`
    mirrors the langgraph-sdk run config (carries `trigger` / overrides).
    """

    input: dict | None = None
    command: dict | None = None
    config: dict | None = None
    output_schema: dict | None = None
    multitask_strategy: MultitaskStrategy = "reject"


#: What a `/runs/stream` consumer gets unless it asks otherwise: the answer's
#: tokens, tool activity, the run's lifecycle and approval requests.
DEFAULT_STREAM_CHANNELS = ["messages", "tools", "lifecycle", "input"]


class RunStreamCreate(RunCreate):
    """Client payload for `POST /threads/{thread_id}/runs/stream` — the
    `/invoke` body plus what to relay.

    `channels` are Agent Streaming Protocol channels. `subagents` also relays
    events from inside subagents (namespaced), which are otherwise dropped.
    Approval requests (`input`) are the exception to both: they are always
    relayed, from every agent.
    """

    channels: list[str] = Field(default_factory=lambda: list(DEFAULT_STREAM_CHANNELS))
    subagents: bool = False

    @field_validator("channels")
    @classmethod
    def _known_channels(cls, channels: list[str]) -> list[str]:
        """A misspelt channel would otherwise just deliver nothing."""
        unknown = [
            c
            for c in channels
            if c not in KNOWN_CHANNELS and not c.startswith("custom:")
        ]
        if unknown:
            raise ValueError(
                f"Unknown channels {unknown}; expected any of {sorted(KNOWN_CHANNELS)} "
                "or custom:<name>."
            )
        return channels


class RunResponse(BaseModel):
    """API projection of a run — operational state only (no input/command)."""

    id: str
    thread_id: str
    status: RunStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: RunDB) -> RunResponse:
        return cls(
            id=record.id,
            thread_id=record.thread_id,
            status=record.status,
            error=record.error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
