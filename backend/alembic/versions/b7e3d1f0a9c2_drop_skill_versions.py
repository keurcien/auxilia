"""Drop skill_versions: a sync now applies upstream changes in place.

Pending versions are not carried over — their skills still differ from
upstream, so the next sync applies them.

Revision ID: b7e3d1f0a9c2
Revises: 8a40e1b2c3d4
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision = "b7e3d1f0a9c2"
down_revision = "8a40e1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index(op.f("ix_skill_versions_digest"), table_name="skill_versions")
    op.drop_index(op.f("ix_skill_versions_skill_id"), table_name="skill_versions")
    op.drop_table("skill_versions")


def downgrade():
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(length=80), nullable=False),
        sa.Column("revision", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "digest", name="uq_skill_versions_digest"),
    )
    op.create_index(
        op.f("ix_skill_versions_skill_id"), "skill_versions", ["skill_id"], unique=False
    )
    op.create_index(
        op.f("ix_skill_versions_digest"), "skill_versions", ["digest"], unique=False
    )
