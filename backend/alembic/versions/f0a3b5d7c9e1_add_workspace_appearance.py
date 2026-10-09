"""add workspace appearance

Revision ID: f0a3b5d7c9e1
Revises: e9f2a4c6b8d0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "f0a3b5d7c9e1"
down_revision: str | Sequence[str] | None = "e9f2a4c6b8d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_appearance",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("app_name", sa.String(length=50), nullable=False),
        sa.Column("logo_data", sa.LargeBinary(), nullable=True),
        sa.Column("logo_media_type", sa.String(length=50), nullable=True),
        sa.Column("logo_sha256", sa.String(length=64), nullable=True),
        sa.Column("logo_revision", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("workspace_appearance")
