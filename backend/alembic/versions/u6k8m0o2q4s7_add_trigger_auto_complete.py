"""add trigger auto complete

Revision ID: u6k8m0o2q4s7
Revises: t5j7l9n1p3r6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "u6k8m0o2q4s7"
down_revision: str | Sequence[str] | None = "t5j7l9n1p3r6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "triggers",
        sa.Column(
            "auto_complete",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "threads",
        sa.Column(
            "complete_on_success",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("threads", "complete_on_success")
    op.drop_column("triggers", "auto_complete")
