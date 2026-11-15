"""add trigger run once

Revision ID: s4i6k8m0o2q5
Revises: r3h5j7l9n1p4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "s4i6k8m0o2q5"
down_revision: str | Sequence[str] | None = "r3h5j7l9n1p4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "triggers",
        sa.Column(
            "run_once",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("triggers", "run_once")
