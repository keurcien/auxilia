from datetime import datetime
from uuid import UUID

from sqlmodel import SQLModel

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


class SchedulePreviewResponse(SQLModel):
    next_run_ats: list[datetime]


class TriggerRunResponse(SQLModel):
    """A manually fired occurrence: the thread it landed in and its run."""

    thread_id: str
    run_id: str
