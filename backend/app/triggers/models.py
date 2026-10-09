from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Index,
    UniqueConstraint,
    text,
)
from sqlmodel import Column, Field, SQLModel, Text

from app.models import BaseDBModel
from app.visibility import ResourceVisibility


class TriggerType(StrEnum):
    schedule = "schedule"
    webhook = "webhook"


class TriggerBase(SQLModel):
    name: str = Field(max_length=255, nullable=False)
    group: str | None = Field(default=None, max_length=255, nullable=True, index=True)
    instructions: str = Field(sa_column=Column(Text, nullable=False))
    agent_id: UUID = Field(
        foreign_key="agents.id", ondelete="CASCADE", index=True, nullable=False
    )
    model_id: str = Field(max_length=255, nullable=False)
    # Reasoning-effort choice for the model, one of its whitelist-declared
    # levels; NULL = the model's default. Copied onto each firing's thread.
    reasoning_effort: str | None = Field(default=None, max_length=32, nullable=True)
    cron_expression: str | None = Field(default=None, max_length=255, nullable=True)
    timezone: str | None = Field(default=None, max_length=64, nullable=True)
    is_active: bool = Field(default=True, nullable=False)


class TriggerDB(TriggerBase, BaseDBModel, table=True):
    __tablename__ = "triggers"
    __table_args__ = (
        CheckConstraint(
            """
            (trigger_type = 'schedule' AND cron_expression IS NOT NULL
                AND timezone IS NOT NULL AND webhook_id IS NULL)
            OR
            (trigger_type = 'webhook' AND cron_expression IS NULL
                AND timezone IS NULL AND next_run_at IS NULL
                AND webhook_id IS NOT NULL)
            """,
            name="ck_triggers_type_fields",
        ),
        # The scanner's hot query (is_active AND next_run_at <= now). Partial:
        # paused triggers have next_run_at NULL and never enter the index.
        Index(
            "ix_triggers_due",
            "next_run_at",
            postgresql_where=text("is_active AND next_run_at IS NOT NULL"),
        ),
    )

    workspace_id: UUID = Field(foreign_key="workspaces.id", nullable=False, index=True)
    owner_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", index=True, nullable=False
    )
    visibility: ResourceVisibility = Field(
        default=ResourceVisibility.personal,
        sa_column=Column(
            SAEnum(ResourceVisibility, native_enum=False, create_constraint=False),
            nullable=False,
            server_default=ResourceVisibility.personal.value,
        ),
    )
    trigger_type: TriggerType = Field(
        default=TriggerType.schedule,
        sa_column=Column(
            SAEnum(TriggerType, native_enum=False, create_constraint=False),
            nullable=False,
        ),
    )
    # The random identifier is the webhook credential. It remains stable so an
    # owner can copy the URL again from the detail page.
    webhook_id: UUID | None = Field(default=None, unique=True, nullable=True)
    # The single materialized next occurrence — the scanner's query key.
    # NULL while the trigger is paused, so paused rows never match the due scan.
    next_run_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_run_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class TriggerTeamDB(BaseDBModel, table=True):
    __tablename__ = "trigger_teams"
    __table_args__ = (
        UniqueConstraint("trigger_id", "team_id", name="uq_trigger_visibility_team"),
    )

    trigger_id: UUID = Field(
        foreign_key="triggers.id", ondelete="CASCADE", nullable=False, index=True
    )
    team_id: UUID = Field(
        foreign_key="teams.id", ondelete="CASCADE", nullable=False, index=True
    )
