"""Wire schemas for the runs API.

Shapes match LangGraph Server v1 where possible (PRD §5). Internal-only fields
(worker_id, heartbeat_at, last_event_id) are deliberately *not* exposed —
clients have no use for them and they leak operational detail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.agents.runs.state import (
    CancellationReason,
    MultitaskStrategy,
    RunState,
)


class RunCreate(BaseModel):
    """Body for ``POST /threads/{tid}/runs[/stream]``.

    Mirrors the LangGraph Server payload: ``input`` for a fresh turn, or
    ``command`` for HITL resume. Exactly one of the two must be set —
    enforced below so downstream code can rely on it.
    ``config.configurable`` may carry our ``trigger=regenerate-message`` flag.
    """

    input: dict[str, Any] | None = None
    command: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    multitask_strategy: MultitaskStrategy = MultitaskStrategy.REJECT

    @model_validator(mode="after")
    def _exactly_one_of_input_or_command(self) -> RunCreate:
        has_input = self.input is not None
        has_command = self.command is not None
        if has_input == has_command:
            raise ValueError(
                "Exactly one of 'input' (new turn) or 'command' (resume from "
                "interrupt) must be provided."
            )
        return self


class RunResponse(BaseModel):
    """Run metadata returned from create / get / list endpoints."""

    run_id: UUID = Field(alias="run_id")
    thread_id: str
    agent_id: UUID
    status: RunState
    multitask_strategy: MultitaskStrategy
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancellation_reason: CancellationReason | None = None
    error: dict[str, Any] | None = None
    interrupt: dict[str, Any] | None = None
    model_id: str | None = None

    model_config = {"populate_by_name": True}
