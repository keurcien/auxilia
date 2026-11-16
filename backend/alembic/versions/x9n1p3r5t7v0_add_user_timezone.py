"""add user timezone

Revision ID: x9n1p3r5t7v0
Revises: w8m0o2q4s6u9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "x9n1p3r5t7v0"
down_revision: str | Sequence[str] | None = "w8m0o2q4s6u9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
