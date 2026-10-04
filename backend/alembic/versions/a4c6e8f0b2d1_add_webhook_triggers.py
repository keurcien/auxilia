"""add webhook triggers

Revision ID: a4c6e8f0b2d1
Revises: a4c7e9f1b3d5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "a4c6e8f0b2d1"
down_revision: str | Sequence[str] | None = "a4c7e9f1b3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "triggers",
        sa.Column(
            "trigger_type",
            sa.String(length=8),
            nullable=False,
            server_default="schedule",
        ),
    )
    op.add_column("triggers", sa.Column("webhook_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        "uq_triggers_webhook_id", "triggers", ["webhook_id"]
    )
    op.alter_column(
        "triggers",
        "cron_expression",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.alter_column(
        "triggers",
        "timezone",
        existing_type=sa.String(length=64),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_triggers_type_fields",
        "triggers",
        """
        (trigger_type = 'schedule' AND cron_expression IS NOT NULL
            AND timezone IS NOT NULL AND webhook_id IS NULL)
        OR
        (trigger_type = 'webhook' AND cron_expression IS NULL
            AND timezone IS NULL AND next_run_at IS NULL
            AND webhook_id IS NOT NULL)
        """,
    )
    op.alter_column("triggers", "trigger_type", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_triggers_type_fields", "triggers", type_="check")
    op.execute("DELETE FROM triggers WHERE trigger_type = 'webhook'")
    op.alter_column(
        "triggers",
        "timezone",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "triggers",
        "cron_expression",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_constraint("uq_triggers_webhook_id", "triggers", type_="unique")
    op.drop_column("triggers", "webhook_id")
    op.drop_column("triggers", "trigger_type")
