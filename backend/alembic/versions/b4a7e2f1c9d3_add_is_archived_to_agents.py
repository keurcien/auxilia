"""add is_archived to agents

Revision ID: b4a7e2f1c9d3
Revises: 0ea6423f4df4
Create Date: 2026-03-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b4a7e2f1c9d3"
down_revision: str | Sequence[str] | None = "0ea6423f4df4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add is_archived boolean column to agents table."""
    op.add_column(
        "agents",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    """Remove is_archived column from agents table."""
    op.drop_column("agents", "is_archived")
