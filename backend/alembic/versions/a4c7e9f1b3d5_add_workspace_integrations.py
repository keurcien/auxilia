"""add workspace integrations

Revision ID: a4c7e9f1b3d5
Revises: f0a3b5d7c9e1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "a4c7e9f1b3d5"
down_revision: str | Sequence[str] | None = "f0a3b5d7c9e1"
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
        "workspace_authentication",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("google_client_id_encrypted", sa.Text(), nullable=True),
        sa.Column("google_client_secret_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "google_exclusive", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "(google_client_id_encrypted IS NULL) = "
            "(google_client_secret_encrypted IS NULL)",
            name="ck_workspace_authentication_google_pair",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "slack_notification_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("bot_token_encrypted", sa.Text(), nullable=True),
        sa.Column("signing_secret_encrypted", sa.Text(), nullable=True),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "(bot_token_encrypted IS NULL) = (signing_secret_encrypted IS NULL)",
            name="ck_slack_notification_credentials_pair",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "workspace_observability",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "base_url",
            sa.String(length=2048),
            server_default="https://cloud.langfuse.com",
            nullable=False,
        ),
        sa.Column("public_key_encrypted", sa.Text(), nullable=True),
        sa.Column("secret_key_encrypted", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), server_default="15", nullable=False),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "(public_key_encrypted IS NULL) = (secret_key_encrypted IS NULL)",
            name="ck_workspace_observability_credentials_pair",
        ),
        sa.CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 120",
            name="ck_workspace_observability_timeout",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("workspace_observability")
    op.drop_table("slack_notification_settings")
    op.drop_table("workspace_authentication")
