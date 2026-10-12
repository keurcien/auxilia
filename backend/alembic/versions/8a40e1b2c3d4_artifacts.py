"""Persist published artifact descriptors (bytes remain outside Postgres).

Revision ID: 8a40e1b2c3d4
Revises: 2376289a83e0
"""

import sqlalchemy as sa

from alembic import op


revision = "8a40e1b2c3d4"
down_revision = "2376289a83e0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
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
        sa.Column(
            "thread_id",
            sa.String(),
            sa.ForeignKey("threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *[
            sa.Column(name, sa.String(), nullable=False)
            for name in [
                "tool_call_id",
                "source_path",
                "title",
                "filename",
                "mime_type",
                "sha256",
                "storage_kind",
                "storage_key",
            ]
        ],
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("storage_bucket", sa.String(), nullable=True),
        sa.Column("storage_endpoint", sa.String(), nullable=True),
        sa.Column(
            "sandbox_source_id",
            sa.Uuid(),
            sa.ForeignKey("sandboxes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sandbox_id", sa.String(), nullable=True),
        sa.UniqueConstraint("thread_id", "tool_call_id", "source_path"),
    )
    op.create_index("ix_artifacts_thread_id", "artifacts", ["thread_id"])


def downgrade():
    op.drop_table("artifacts")
