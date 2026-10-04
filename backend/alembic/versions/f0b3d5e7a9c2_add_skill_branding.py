"""add skill branding

Revision ID: f0b3d5e7a9c2
Revises: e9a2c4f6b8d1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "f0b3d5e7a9c2"
down_revision: str | Sequence[str] | None = "e9a2c4f6b8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("emoji", sa.String(length=10), nullable=True))
    op.add_column("skills", sa.Column("color", sa.String(length=7), nullable=True))
    op.add_column("skills", sa.Column("image_revision", sa.Uuid(), nullable=True))
    op.create_table(
        "skill_images",
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
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", name="uq_skill_image_skill_id"),
    )
    op.create_index(
        "ix_skill_images_skill_id",
        "skill_images",
        ["skill_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_skill_images_skill_id", table_name="skill_images")
    op.drop_table("skill_images")
    op.drop_column("skills", "image_revision")
    op.drop_column("skills", "color")
    op.drop_column("skills", "emoji")
