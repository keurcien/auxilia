from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.agents.runs.models import RunDB
from app.agents.runs.state import RunStatus


class RunCreate(BaseModel):
    """Client payload for `POST /threads/{thread_id}/runs`.

    `input` starts a new turn; `command` resumes a HITL interrupt. `config`
    mirrors the langgraph-sdk run config (carries `trigger` / overrides).
    """

    input: dict | None = None
    command: dict | None = None
    config: dict | None = None
    multitask_strategy: Literal["reject", "enqueue"] = "reject"


class RunResponse(BaseModel):
    """API projection of a run — operational state only (no input/command)."""

    id: str
    thread_id: str
    status: RunStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: RunDB) -> "RunResponse":
        return cls(
            id=record.id,
            thread_id=record.thread_id,
            status=record.status,
            error=record.error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
