"""add thread deletion permission

Revision ID: i4e6a8c0b2d5
Revises: h3d5f7a9b1c4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "i4e6a8c0b2d5"
down_revision: str | Sequence[str] | None = "h3d5f7a9b1c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "can_delete_threads",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "can_delete_threads")
