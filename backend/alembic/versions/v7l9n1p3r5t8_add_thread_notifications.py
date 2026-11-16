"""add thread notifications

Revision ID: v7l9n1p3r5t8
Revises: u6k8m0o2q4s7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "v7l9n1p3r5t8"
down_revision: str | Sequence[str] | None = "u6k8m0o2q4s7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "threads",
        sa.Column("notifications_enabled", sa.Boolean(), nullable=True),
    )
    # Existing threads keep what they would have received: the owner's account
    # setting, and for trigger firings the trigger's own setting as well.
    op.execute(
        """
        UPDATE threads
        SET notifications_enabled = users.notifications_enabled
        FROM users
        WHERE users.id = threads.user_id
        """
    )
    op.execute(
        """
        UPDATE threads
        SET notifications_enabled = false
        FROM triggers
        WHERE triggers.id = threads.trigger_id
          AND NOT triggers.notifications_enabled
        """
    )


def downgrade() -> None:
    op.drop_column("threads", "notifications_enabled")
