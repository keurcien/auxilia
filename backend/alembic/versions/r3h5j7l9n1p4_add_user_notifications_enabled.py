"""add user notifications enabled

Revision ID: r3h5j7l9n1p4
Revises: q2g4i6k8m0o3
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "r3h5j7l9n1p4"
down_revision: str | Sequence[str] | None = "q2g4i6k8m0o3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "notifications_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notifications_enabled")
