from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel

from app.runtime.runs.state import RunStatus
from app.triggers.models import TriggerBase, TriggerType
from app.visibility import ResourceVisibility


def _normalize_group(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "/".join(part.strip() for part in value.split("/") if part.strip())
    if len(normalized) > 255:
        raise ValueError("group must be at most 255 characters")
    return normalized or None


class TriggerCreate(TriggerBase):
    trigger_type: TriggerType = TriggerType.schedule
    visibility: ResourceVisibility = ResourceVisibility.personal
    team_ids: list[UUID] = Field(default_factory=list, exclude=True)

    @field_validator("group")
    @classmethod
    def normalize_group(cls, value: str | None) -> str | None:
        return _normalize_group(value)

    @model_validator(mode="after")
    def validate_type_fields(self) -> "TriggerCreate":
        if self.trigger_type == TriggerType.schedule:
            if not self.cron_expression or not self.timezone:
                raise ValueError("Scheduled triggers require a schedule and timezone")
        elif self.cron_expression is not None or self.timezone is not None:
            raise ValueError("Webhook triggers cannot define a schedule or timezone")
        return self


class TriggerCreateDB(TriggerBase):
    workspace_id: UUID
    owner_id: UUID
    visibility: ResourceVisibility = ResourceVisibility.personal
    trigger_type: TriggerType
    webhook_id: UUID | None = None
    next_run_at: datetime | None = None


class TriggerPatch(SQLModel):
    name: str | None = None
    group: str | None = None
    instructions: str | None = None
    agent_id: UUID | None = None
    model_id: str | None = None
    reasoning_effort: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    is_active: bool | None = None
    visibility: ResourceVisibility | None = None
    team_ids: list[UUID] | None = Field(default=None, exclude=True)

    @field_validator("group")
    @classmethod
    def normalize_group(cls, value: str | None) -> str | None:
        return _normalize_group(value)


class TriggerResponse(SQLModel):
    id: UUID
    workspace_id: UUID
    name: str
    group: str | None = None
    instructions: str
    owner_id: UUID
    visibility: ResourceVisibility = ResourceVisibility.personal
    team_ids: list[UUID] = Field(default_factory=list)
    agent_id: UUID
    model_id: str
    reasoning_effort: str | None = None
    trigger_type: TriggerType
    cron_expression: str | None = None
    timezone: str | None = None
    webhook_url: str | None = None
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
    can_manage: bool = False


class SchedulePreviewResponse(SQLModel):
    next_run_ats: list[datetime]


class TriggerRunResponse(SQLModel):
    """A manually fired occurrence: the thread it landed in and its run."""

    thread_id: str
    run_id: str


class WebhookTriggerInvoke(SQLModel):
    """Per-call overrides accepted by a webhook trigger."""

    model_config = ConfigDict(extra="forbid")  # type: ignore[assignment]

    agent_id: UUID | None = None
    model_id: str | None = Field(default=None, max_length=255)
    instructions: str | None = None


class TriggerThreadResponse(SQLModel):
    """One past firing of a trigger — the thread it created."""

    id: str
    agent_id: UUID
    first_message_content: str | None = None
    # Outcome of the firing's run; None while in flight.
    last_run_status: RunStatus | None = None
    created_at: datetime
