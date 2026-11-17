"""trigger model_id nullable (follow the agent or workspace default)

Revision ID: y0p2r4t6v8x1
Revises: x9n1p3r5t7v0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "y0p2r4t6v8x1"
down_revision: str | Sequence[str] | None = "x9n1p3r5t7v0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "triggers",
        "model_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    # Pin default-following triggers to their workspace default; any left over
    # (no default flagged) cannot be represented and are removed.
    op.execute(
        """
        UPDATE triggers SET model_id = models.model_id
        FROM models
        WHERE triggers.model_id IS NULL
          AND models.workspace_id = triggers.workspace_id
          AND models.is_default
        """
    )
    op.execute("DELETE FROM triggers WHERE model_id IS NULL")
    op.alter_column(
        "triggers",
        "model_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
