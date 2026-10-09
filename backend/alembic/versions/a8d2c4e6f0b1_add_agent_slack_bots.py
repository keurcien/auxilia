"""add agent Slack bots

Revision ID: a8d2c4e6f0b1
Revises: f7a9c3e5b2d8
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "a8d2c4e6f0b1"
down_revision: str | Sequence[str] | None = "f7a9c3e5b2d8"
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


def upgrade() -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        "agent_slack_bots",
        sa.Column("id", sa.Uuid(), nullable=False),
        created_at,
        updated_at,
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=False),
        sa.Column("signing_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("slack_team_id", sa.String(length=64), nullable=False),
        sa.Column("slack_team_name", sa.String(length=255), nullable=True),
        sa.Column("bot_user_id", sa.String(length=64), nullable=False),
        sa.Column("bot_name", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_slack_bot_agent"),
        sa.UniqueConstraint(
            "slack_team_id",
            "bot_user_id",
            name="uq_agent_slack_bot_installation",
        ),
    )
    op.create_index(
        op.f("ix_agent_slack_bots_agent_id"),
        "agent_slack_bots",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_slack_bots_slack_team_id"),
        "agent_slack_bots",
        ["slack_team_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_slack_bots_workspace_id"),
        "agent_slack_bots",
        ["workspace_id"],
        unique=False,
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "slack_thread_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        created_at,
        updated_at,
        sa.Column("slack_bot_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("slack_thread_ts", sa.String(length=64), nullable=False),
        sa.Column("slack_user_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["slack_bot_id"], ["agent_slack_bots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["threads.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "slack_bot_id",
            "channel_id",
            "slack_thread_ts",
            name="uq_slack_thread_external",
        ),
        sa.UniqueConstraint("thread_id", name="uq_slack_thread_internal"),
    )
    op.create_index(
        op.f("ix_slack_thread_bindings_slack_bot_id"),
        "slack_thread_bindings",
        ["slack_bot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_slack_thread_bindings_thread_id"),
        "slack_thread_bindings",
        ["thread_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_slack_thread_bindings_thread_id"),
        table_name="slack_thread_bindings",
    )
    op.drop_index(
        op.f("ix_slack_thread_bindings_slack_bot_id"),
        table_name="slack_thread_bindings",
    )
    op.drop_table("slack_thread_bindings")
    op.drop_index(
        op.f("ix_agent_slack_bots_workspace_id"), table_name="agent_slack_bots"
    )
    op.drop_index(
        op.f("ix_agent_slack_bots_slack_team_id"), table_name="agent_slack_bots"
    )
    op.drop_index(
        op.f("ix_agent_slack_bots_agent_id"), table_name="agent_slack_bots"
    )
    op.drop_table("agent_slack_bots")
