"""Audit table for runs.

Postgres is the *history* store: every state transition is mirrored from the
Redis live record into a row here. Redis is hot, ephemeral, optimised for the
producer/consumer hot path; Postgres is slow, durable, optimised for billing,
support, and admin queries.

The columns intentionally mirror ``RunRecord`` (state.py). When the Redis hash
expires, the Postgres row remains the canonical record of "this run happened".
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from app.agents.runs.state import (
    CancellationReason,
    MultitaskStrategy,
    RunState,
)
from app.models import TimestampMixin


class RunDB(TimestampMixin, SQLModel, table=True):
    __tablename__ = "runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    thread_id: str = Field(foreign_key="threads.id", nullable=False, index=True)
    user_id: UUID = Field(foreign_key="users.id", nullable=False, index=True)
    agent_id: UUID = Field(foreign_key="agents.id", nullable=False)

    status: RunState = Field(default=RunState.PENDING, nullable=False, index=True)
    multitask_strategy: MultitaskStrategy = Field(
        default=MultitaskStrategy.REJECT, nullable=False
    )

    started_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    cancellation_reason: CancellationReason | None = Field(default=None, nullable=True)
    error: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    interrupt: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    input_summary: dict | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )

    model_id: str | None = Field(default=None, nullable=True)
    token_usage: dict | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
