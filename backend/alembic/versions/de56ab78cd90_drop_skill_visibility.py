"""Drop skill visibility: every skill is readable by the whole workspace.

Revision ID: de56ab78cd90
Revises: cd34ef56ab78
"""

import sqlalchemy as sa

from alembic import op


revision = "de56ab78cd90"
down_revision = "cd34ef56ab78"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("skills", "visibility")


def downgrade():
    # Skills were workspace-readable while the column was gone; keep them so.
    op.add_column(
        "skills",
        sa.Column(
            "visibility", sa.String(), nullable=False, server_default="workspace"
        ),
    )
    op.alter_column("skills", "visibility", server_default=None)
