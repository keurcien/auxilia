"""pause prompt queue while editing

Revision ID: b2d5f7a9c1e3
Revises: a1c4e6f8b0d2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "b2d5f7a9c1e3"
down_revision: str | Sequence[str] | None = "a1c4e6f8b0d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "threads",
        sa.Column("queue_edit_run_id", sa.String(), nullable=True),
    )
    op.add_column(
        "threads",
        sa.Column(
            "queue_edit_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("threads", "queue_edit_expires_at")
    op.drop_column("threads", "queue_edit_run_id")
