from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, text
from sqlmodel import Column, Field, SQLModel, Text

from app.models import BaseDBModel


class TriggerBase(SQLModel):
    name: str = Field(max_length=255, nullable=False)
    instructions: str = Field(sa_column=Column(Text, nullable=False))
    agent_id: UUID = Field(
        foreign_key="agents.id", ondelete="CASCADE", index=True, nullable=False
    )
    model_id: str = Field(max_length=255, nullable=False)
    cron_expression: str = Field(max_length=255, nullable=False)
    timezone: str = Field(default="UTC", max_length=64, nullable=False)
    is_active: bool = Field(default=True, nullable=False)


class TriggerDB(TriggerBase, BaseDBModel, table=True):
    __tablename__ = "triggers"
    __table_args__ = (
        # The scanner's hot query (is_active AND next_run_at <= now). Partial:
        # paused triggers have next_run_at NULL and never enter the index.
        Index(
            "ix_triggers_due",
            "next_run_at",
            postgresql_where=text("is_active AND next_run_at IS NOT NULL"),
        ),
    )

    owner_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", index=True, nullable=False
    )
    # The single materialized next occurrence — the scanner's query key.
    # NULL while the trigger is paused, so paused rows never match the due scan.
    next_run_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_run_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
