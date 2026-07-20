from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

from app.agents.runs.state import RunStatus
from app.triggers.models import TriggerBase


class TriggerCreate(TriggerBase):
    pass


class TriggerCreateDB(TriggerBase):
    owner_id: UUID
    next_run_at: datetime | None = None


class TriggerPatch(SQLModel):
    name: str | None = None
    instructions: str | None = None
    agent_id: UUID | None = None
    model_id: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    is_active: bool | None = None


class TriggerResponse(SQLModel):
    id: UUID
    name: str
    instructions: str
    owner_id: UUID
    agent_id: UUID
    model_id: str
    cron_expression: str
    timezone: str
    is_active: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Whether the trigger's model can run right now (whitelist ∧ provider key
    # ∧ admin-enabled). Server-computed on every read so the UI can warn
    # preemptively — a trigger with an unavailable model has its scheduled
    # firings skipped by the scanner.
    model_available: bool = True
    # Whitelist display name for model_id (set even when unavailable, so the
    # UI never has to show a raw id). None = not in the whitelist at all —
    # clients fall back to model_id.
    model_display_name: str | None = None


class SchedulePreviewResponse(SQLModel):
    next_run_ats: list[datetime]


class TriggerRunResponse(SQLModel):
    """A manually fired occurrence: the thread it landed in and its run."""

    thread_id: str
    run_id: str


class TriggerThreadResponse(SQLModel):
    """One past firing of a trigger — the thread it created."""

    id: str
    agent_id: UUID
    first_message_content: str | None = None
    # Outcome of the firing's run; None while in flight.
    last_run_status: RunStatus | None = None
    created_at: datetime
