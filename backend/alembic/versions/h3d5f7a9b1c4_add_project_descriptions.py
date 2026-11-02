"""add project descriptions

Revision ID: h3d5f7a9b1c4
Revises: g2c4e6a8b0d3
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "h3d5f7a9b1c4"
down_revision: str | Sequence[str] | None = "g2c4e6a8b0d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "description",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "description")
