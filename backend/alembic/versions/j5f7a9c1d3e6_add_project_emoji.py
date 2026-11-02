"""add project emoji

Revision ID: j5f7a9c1d3e6
Revises: i4e6a8c0b2d5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "j5f7a9c1d3e6"
down_revision: str | Sequence[str] | None = "i4e6a8c0b2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("emoji", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "emoji")
