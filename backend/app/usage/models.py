from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models import BaseDBModel


class UsageChannel(StrEnum):
    """Where a model call came from. Trigger threads split by trigger type."""

    web = "web"
    api = "api"
    slack = "slack"
    telegram = "telegram"
    whatsapp = "whatsapp"
    schedule = "schedule"
    webhook = "webhook"
    # A trigger thread whose trigger was deleted before its type was known.
    trigger = "trigger"


def _tokens_column() -> Column:
    return Column(BigInteger, nullable=False, server_default="0")


class LLMUsageDB(BaseDBModel, table=True):
    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_workspace_occurred_at", "workspace_id", "occurred_at"),
        # NULLs are distinct, so calls without a message id never conflict;
        # recorded and backfilled copies of the same call do.
        UniqueConstraint("thread_id", "message_id", name="uq_llm_usage_thread_message"),
    )

    workspace_id: UUID = Field(
        foreign_key="workspaces.id", ondelete="CASCADE", nullable=False
    )
    occurred_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    # Attribution survives deletion of what it points at: spend stays spent.
    thread_id: str | None = Field(
        default=None, foreign_key="threads.id", ondelete="SET NULL", nullable=True
    )
    message_id: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    user_id: UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL", index=True
    )
    agent_id: UUID | None = Field(
        default=None, foreign_key="agents.id", ondelete="SET NULL", index=True
    )
    project_id: UUID | None = Field(
        default=None, foreign_key="projects.id", ondelete="SET NULL", index=True
    )
    trigger_id: UUID | None = Field(
        default=None, foreign_key="triggers.id", ondelete="SET NULL", index=True
    )
    channel: str = Field(sa_column=Column(String(32), nullable=False))
    model_id: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    # Disjoint buckets: uncached input + cache read + cache write + output = total.
    input_tokens: int = Field(default=0, sa_column=_tokens_column())
    cache_read_tokens: int = Field(default=0, sa_column=_tokens_column())
    cache_creation_tokens: int = Field(default=0, sa_column=_tokens_column())
    output_tokens: int = Field(default=0, sa_column=_tokens_column())
    total_tokens: int = Field(default=0, sa_column=_tokens_column())
    # USD at the catalog price of the moment; NULL when the model had no price.
    cost_usd: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(20, 10), nullable=True)
    )


class UsageSettingsDB(BaseDBModel, table=True):
    __tablename__ = "workspace_usage_settings"
    __table_args__ = (
        CheckConstraint("usd_rate > 0", name="ck_workspace_usage_settings_rate"),
        CheckConstraint(
            "monthly_budget IS NULL OR monthly_budget > 0",
            name="ck_workspace_usage_settings_budget",
        ),
    )

    workspace_id: UUID = Field(
        foreign_key="workspaces.id", ondelete="CASCADE", unique=True, nullable=False
    )
    currency: str = Field(sa_column=Column(String(3), nullable=False))
    # Display currency units per USD; catalog prices are USD.
    usd_rate: Decimal = Field(sa_column=Column(Numeric(12, 6), nullable=False))
    # In the display currency.
    monthly_budget: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(14, 2), nullable=True)
    )


class UsageLedgerStateDB(SQLModel, table=True):
    """Single row: when live recording started and whether history was imported."""

    __tablename__ = "llm_usage_state"

    id: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    tracking_started_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    backfill_completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
