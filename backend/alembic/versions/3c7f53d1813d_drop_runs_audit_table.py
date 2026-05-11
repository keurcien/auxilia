"""drop runs audit table

Revision ID: 3c7f53d1813d
Revises: 448c4c508f8d
Create Date: 2026-05-08

The Postgres ``runs`` table was a write-only audit mirror of the Redis run
hash. In practice nothing in the codebase queried it: cost telemetry runs
through Langfuse, conversation state through the LangGraph checkpoint, and
live status through Redis. Keeping the table meant writing audit-sync code
in the worker and managing FK constraints for a row no consumer ever read.

This migration drops the table and the three enum types it owned. Downgrade
recreates them in the original shape (including the cascade FK that landed
in revision 448c4c508f8d) so the previous schema can be restored if needed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "3c7f53d1813d"
down_revision: Union[str, Sequence[str], None] = "448c4c508f8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_runs_user_id"), table_name="runs")
    op.drop_index(op.f("ix_runs_thread_id"), table_name="runs")
    op.drop_index(op.f("ix_runs_status"), table_name="runs")
    op.drop_table("runs")
    op.execute("DROP TYPE IF EXISTS runstate")
    op.execute("DROP TYPE IF EXISTS multitaskstrategy")
    op.execute("DROP TYPE IF EXISTS cancellationreason")


def downgrade() -> None:
    op.create_table(
        "runs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "RUNNING", "INTERRUPTED", "SUCCESS",
                "ERROR", "CANCELLED", "TIMEOUT", name="runstate",
            ),
            nullable=False,
        ),
        sa.Column(
            "multitask_strategy",
            sa.Enum(
                "REJECT", "ENQUEUE", "INTERRUPT", "ROLLBACK",
                name="multitaskstrategy",
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancellation_reason",
            sa.Enum("USER", "REPLACED", "TIMEOUT", "SYSTEM", name="cancellationreason"),
            nullable=True,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("interrupt", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runs_status"), "runs", ["status"], unique=False)
    op.create_index(op.f("ix_runs_thread_id"), "runs", ["thread_id"], unique=False)
    op.create_index(op.f("ix_runs_user_id"), "runs", ["user_id"], unique=False)
