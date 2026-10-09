from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

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
    multitask_strategy: MultitaskStrategy = "reject"


class RunResponse(BaseModel):
    """API projection of a run — operational state only (no input/command)."""

    id: str
    workspace_id: UUID
    thread_id: str
    status: RunStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: RunDB) -> "RunResponse":
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            thread_id=record.thread_id,
            status=record.status,
            error=record.error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class QueuedPromptCreate(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class QueuedPromptPatch(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class QueuedPromptOrder(BaseModel):
    ordered_ids: list[str]


class QueuedPromptResponse(BaseModel):
    id: str
    text: str
    position: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: RunDB) -> "QueuedPromptResponse | None":
        messages = (record.input or {}).get("messages")
        if not isinstance(messages, list) or len(messages) != 1:
            return None
        message = messages[0]
        if not isinstance(message, dict) or message.get("type") != "human":
            return None
        content = message.get("content")
        if not isinstance(content, str) or record.queue_position is None:
            return None
        return cls(
            id=record.id,
            text=content,
            position=record.queue_position,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


def queued_prompt_input(text: str) -> dict:
    return {"messages": [{"type": "human", "content": text}]}
