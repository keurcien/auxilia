"""Artifacts hold thread files: user attachments next to agent artifacts.

Revision ID: c4d8e2f1a7b3
Revises: b7e3d1f0a9c2
"""

import sqlalchemy as sa

from alembic import op


revision = "c4d8e2f1a7b3"
down_revision = "b7e3d1f0a9c2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "artifacts",
        sa.Column("origin", sa.String(), nullable=False, server_default="artifact"),
    )
    op.alter_column("artifacts", "tool_call_id", nullable=True)


def downgrade():
    # Attachments have no tool call to restore the NOT NULL with.
    op.execute("DELETE FROM artifacts WHERE origin = 'attachment'")
    op.alter_column("artifacts", "tool_call_id", nullable=False)
    op.drop_column("artifacts", "origin")
