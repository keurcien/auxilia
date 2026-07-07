"""RunDB — the durable record of one agent turn.

The run *record* (status, replay parameters, error) lives in Postgres; the
run's ephemeral coordination (event log, cancel signal, liveness) stays in
Redis. See `SPEC.md`.
"""

from uuid import UUID, uuid4

from sqlalchemy import JSON, Enum as SAEnum, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel, String, Text

from app.agents.runs.state import RunStatus
from app.models import TimestampMixin


# JSONB on Postgres; plain JSON elsewhere (the test suite runs on SQLite).
def _json_column() -> Column:
    return Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)


class RunDB(TimestampMixin, SQLModel, table=True):
    __tablename__ = "runs"
    # Mirrors the `add_runs_table` migration so autogenerate never reads the
    # runs indexes as drift. `sqlite_where` keeps the partial semantics in the
    # (SQLite-backed) test suite too.
    __table_args__ = (
        # Run history per thread, newest first.
        Index("ix_runs_thread_id_created_at", "thread_id", "created_at"),
        # The per-thread mutex: at most one running run per thread.
        Index(
            "uq_runs_one_running_per_thread",
            "thread_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
        # The hot set: dispatcher claim + active-runs poll + reaper worklist.
        Index(
            "ix_runs_active",
            "status",
            "user_id",
            postgresql_where=text("status IN ('pending', 'running')"),
            sqlite_where=text("status IN ('pending', 'running')"),
        ),
    )

    # String ids (uuid4) rather than UUID columns: run ids travel through Redis
    # keys, SSE headers, and URL paths as strings, and `threads.id` is already a
    # String — matching it avoids conversions at every seam.
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        sa_column=Column(String, primary_key=True),
    )
    thread_id: str = Field(foreign_key="threads.id", ondelete="CASCADE", nullable=False)
    user_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", nullable=False)
    # Non-native enum: plain VARCHAR in the DB (no pg enum type to migrate),
    # but rows load back as `RunStatus` members — `is_terminal` et al. depend
    # on that (str-enum members don't hash equal to their raw strings).
    status: RunStatus = Field(
        default=RunStatus.pending,
        sa_column=Column(
            SAEnum(RunStatus, native_enum=False, create_constraint=False),
            nullable=False,
        ),
    )
    multitask_strategy: str = Field(
        default="reject", sa_column=Column(String, nullable=False)
    )

    # Run parameters (mutually: input for a new turn, command for a HITL
    # resume) — the worker replays them into `Agent.stream(...)`, and they stay
    # readable afterwards so a failed run can be reproduced.
    input: dict | None = Field(default=None, sa_column=_json_column())
    command: dict | None = Field(default=None, sa_column=_json_column())
    trigger: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    config_overrides: dict | None = Field(default=None, sa_column=_json_column())
    # JSON Schema for a structured final answer (the invoke consumer reads it back).
    output_schema: dict | None = Field(default=None, sa_column=_json_column())
    # Opaque push-delivery descriptor. `None` = pull (an HTTP subscriber rides
    # the event log). A push channel (e.g. Slack) sets it so the worker spawns a
    # delivery consumer; the schema is owned by that channel, not by this module.
    delivery: dict | None = Field(default=None, sa_column=_json_column())

    # Terminal error text, when status is `error`/`timeout`.
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
