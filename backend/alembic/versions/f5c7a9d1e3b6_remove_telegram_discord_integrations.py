"""remove telegram and discord integrations

Revision ID: f5c7a9d1e3b6
Revises: e2a4c6f8b0d1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "f5c7a9d1e3b6"
down_revision: str | Sequence[str] | None = "e2a4c6f8b0d1"
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
    op.drop_table("external_actions")
    op.drop_table("external_conversations")
    op.drop_table("external_identities")
    op.drop_table("discord_notification_settings")
    op.drop_table("telegram_notification_settings")
    op.execute("DELETE FROM threads WHERE source IN ('telegram', 'discord')")


def downgrade() -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        "telegram_notification_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), server_default="default", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("bot_id", sa.String(), nullable=True),
        sa.Column("bot_username", sa.String(), nullable=True),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=True),
        sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "key",
            name="uq_telegram_notifications_workspace_key",
        ),
    )
    op.create_index(
        "ix_telegram_notification_settings_workspace_id",
        "telegram_notification_settings",
        ["workspace_id"],
    )
    op.create_index(
        "ix_telegram_notification_settings_bot_id",
        "telegram_notification_settings",
        ["bot_id"],
        unique=True,
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "discord_notification_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), server_default="default", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("application_id", sa.String(), nullable=True),
        sa.Column("bot_user_id", sa.String(), nullable=True),
        sa.Column("bot_username", sa.String(), nullable=True),
        sa.Column("public_key", sa.String(), nullable=True),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=True),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "key",
            name="uq_discord_notifications_workspace_key",
        ),
    )
    op.create_index(
        "ix_discord_notification_settings_workspace_id",
        "discord_notification_settings",
        ["workspace_id"],
    )
    op.create_index(
        "ix_discord_notification_settings_application_id",
        "discord_notification_settings",
        ["application_id"],
        unique=True,
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_user_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_user_id",
            name="uq_external_identity_provider_user",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "user_id",
            name="uq_external_identity_internal_user",
        ),
    )
    op.create_index(
        "ix_external_identities_workspace_id",
        "external_identities",
        ["workspace_id"],
    )
    op.create_index(
        "ix_external_identities_external_user_id",
        "external_identities",
        ["external_user_id"],
    )
    op.create_index(
        "ix_external_identities_user_id",
        "external_identities",
        ["user_id"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "external_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_chat_id", sa.String(), nullable=False),
        sa.Column("external_thread_id", sa.String(), server_default="", nullable=False),
        sa.Column("external_user_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_chat_id",
            "external_thread_id",
            "external_user_id",
            name="uq_external_conversation_scope",
        ),
        sa.UniqueConstraint(
            "thread_id",
            name="uq_external_conversation_thread",
        ),
    )
    op.create_index(
        "ix_external_conversations_workspace_id",
        "external_conversations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_external_conversations_external_chat_id",
        "external_conversations",
        ["external_chat_id"],
    )
    op.create_index(
        "ix_external_conversations_external_user_id",
        "external_conversations",
        ["external_user_id"],
    )
    op.create_index(
        "ix_external_conversations_thread_id",
        "external_conversations",
        ["thread_id"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "external_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("token", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("interrupt_id", sa.String(), nullable=False),
        sa.Column("tool_call_id", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "token",
            name="uq_external_action_provider_token",
        ),
    )
    op.create_index(
        "ix_external_actions_workspace_id",
        "external_actions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_external_actions_thread_id",
        "external_actions",
        ["thread_id"],
    )
    op.create_index(
        "ix_external_actions_token",
        "external_actions",
        ["token"],
    )
