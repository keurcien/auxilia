"""Threads remember their sandbox: the runtime reconnects on every run.

Revision ID: ef67ab89cd01
Revises: de56ab78cd90
"""

import sqlalchemy as sa

from alembic import op


revision = "ef67ab89cd01"
down_revision = "de56ab78cd90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("threads", sa.Column("sandbox_id", sa.String(), nullable=True))


def downgrade():
    op.drop_column("threads", "sandbox_id")
