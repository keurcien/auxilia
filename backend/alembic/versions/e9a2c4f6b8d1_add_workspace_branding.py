"""add workspace branding

Revision ID: e9a2c4f6b8d1
Revises: d8f1a3c5e7b9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "e9a2c4f6b8d1"
down_revision: str | Sequence[str] | None = "d8f1a3c5e7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("emoji", sa.String(length=10), nullable=True))
    op.add_column("workspaces", sa.Column("color", sa.String(length=7), nullable=True))
    op.add_column("workspaces", sa.Column("image_revision", sa.Uuid(), nullable=True))
    op.create_table(
        "workspace_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            name="uq_workspace_image_workspace_id",
        ),
    )
    op.create_index(
        "ix_workspace_images_workspace_id",
        "workspace_images",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_images_workspace_id",
        table_name="workspace_images",
    )
    op.drop_table("workspace_images")
    op.drop_column("workspaces", "image_revision")
    op.drop_column("workspaces", "color")
    op.drop_column("workspaces", "emoji")
