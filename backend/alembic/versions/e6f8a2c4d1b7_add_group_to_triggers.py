"""add group to triggers

Revision ID: e6f8a2c4d1b7
Revises: c4e8a1b6d2f9
Create Date: 2026-10-04 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "e6f8a2c4d1b7"
down_revision: str | Sequence[str] | None = "c4e8a1b6d2f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("triggers", sa.Column("group", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_triggers_group"), "triggers", ["group"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_triggers_group"), table_name="triggers")
    op.drop_column("triggers", "group")
