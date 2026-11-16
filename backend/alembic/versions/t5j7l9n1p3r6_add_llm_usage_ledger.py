"""add llm usage ledger

Revision ID: t5j7l9n1p3r6
Revises: s4i6k8m0o2q5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "t5j7l9n1p3r6"
down_revision: str | Sequence[str] | None = "s4i6k8m0o2q5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def _tokens(name: str) -> sa.Column:
    return sa.Column(name, sa.BigInteger(), server_default="0", nullable=False)


def upgrade() -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("trigger_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=True),
        _tokens("input_tokens"),
        _tokens("cache_read_tokens"),
        _tokens("cache_creation_tokens"),
        _tokens("output_tokens"),
        _tokens("total_tokens"),
        sa.Column("cost_usd", sa.Numeric(20, 10), nullable=True),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["trigger_id"], ["triggers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id", "message_id", name="uq_llm_usage_thread_message"
        ),
    )
    op.create_index(
        "ix_llm_usage_workspace_occurred_at",
        "llm_usage",
        ["workspace_id", "occurred_at"],
    )
    for column in ("user_id", "agent_id", "project_id", "trigger_id"):
        op.create_index(f"ix_llm_usage_{column}", "llm_usage", [column])

    created_at, updated_at = _timestamps()
    op.create_table(
        "workspace_usage_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("usd_rate", sa.Numeric(12, 6), nullable=False),
        sa.Column("monthly_budget", sa.Numeric(14, 2), nullable=True),
        created_at,
        updated_at,
        sa.CheckConstraint("usd_rate > 0", name="ck_workspace_usage_settings_rate"),
        sa.CheckConstraint(
            "monthly_budget IS NULL OR monthly_budget > 0",
            name="ck_workspace_usage_settings_budget",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id"),
    )

    op.create_table(
        "llm_usage_state",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("tracking_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("backfill_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO llm_usage_state (id, tracking_started_at) VALUES (1, now())"
    )


def downgrade() -> None:
    op.drop_table("llm_usage_state")
    op.drop_table("workspace_usage_settings")
    for column in ("trigger_id", "project_id", "agent_id", "user_id"):
        op.drop_index(f"ix_llm_usage_{column}", table_name="llm_usage")
    op.drop_index("ix_llm_usage_workspace_occurred_at", table_name="llm_usage")
    op.drop_table("llm_usage")
