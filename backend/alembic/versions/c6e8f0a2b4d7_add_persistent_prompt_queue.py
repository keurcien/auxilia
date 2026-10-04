"""add persistent prompt queue

Revision ID: c6e8f0a2b4d7
Revises: b5d7f9a1c3e2
Create Date: 2026-10-03 05:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "c6e8f0a2b4d7"
down_revision: str | Sequence[str] | None = "b5d7f9a1c3e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "threads",
        sa.Column(
            "prompt_queue_counter",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "threads",
        sa.Column(
            "awaiting_input",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE threads SET awaiting_input = true "
            "WHERE last_run_status = 'interrupted'"
        )
    )
    op.add_column("runs", sa.Column("queue_position", sa.BigInteger(), nullable=True))
    op.add_column(
        "runs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text("UPDATE runs SET started_at = created_at WHERE status != 'pending'")
    )
    # Earlier JSON columns encoded Python None as the JSON literal null. Queue
    # eligibility and the active-command index require actual SQL NULLs.
    op.execute(
        sa.text("UPDATE runs SET input = NULL WHERE input = CAST('null' AS jsonb)")
    )
    op.execute(
        sa.text("UPDATE runs SET command = NULL WHERE command = CAST('null' AS jsonb)")
    )
    op.create_index(
        "ix_runs_pending_queue",
        "runs",
        ["thread_id", "queue_position"],
        unique=False,
        postgresql_where=sa.text("status = 'pending' AND queue_position IS NOT NULL"),
    )
    op.create_index(
        "ix_runs_thread_id_started_at",
        "runs",
        ["thread_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "uq_runs_one_active_command_per_thread",
        "runs",
        ["thread_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'running') AND command IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_runs_one_active_command_per_thread", table_name="runs")
    op.drop_index("ix_runs_thread_id_started_at", table_name="runs")
    op.drop_index("ix_runs_pending_queue", table_name="runs")
    op.drop_column("runs", "started_at")
    op.drop_column("runs", "queue_position")
    op.drop_column("threads", "awaiting_input")
    op.drop_column("threads", "prompt_queue_counter")
