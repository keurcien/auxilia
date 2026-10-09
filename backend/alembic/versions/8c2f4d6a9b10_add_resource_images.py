"""add resource images

Revision ID: 8c2f4d6a9b10
Revises: 2376289a83e0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "8c2f4d6a9b10"
down_revision: str | Sequence[str] | None = "2376289a83e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_image_table(
    table_name: str,
    owner_column: str,
    owner_table: str,
    unique_name: str,
) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.Column(owner_column, sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            [owner_column], [f"{owner_table}.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(owner_column, name=unique_name),
    )
    op.create_index(
        op.f(f"ix_{table_name}_{owner_column}"),
        table_name,
        [owner_column],
        unique=False,
    )


def upgrade() -> None:
    op.add_column("agents", sa.Column("image_revision", sa.Uuid(), nullable=True))
    op.add_column("mcp_servers", sa.Column("image_revision", sa.Uuid(), nullable=True))
    _create_image_table("agent_images", "agent_id", "agents", "uq_agent_image_agent_id")
    _create_image_table(
        "mcp_server_images",
        "mcp_server_id",
        "mcp_servers",
        "uq_mcp_server_image_server_id",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mcp_server_images_mcp_server_id"),
        table_name="mcp_server_images",
    )
    op.drop_table("mcp_server_images")
    op.drop_index(op.f("ix_agent_images_agent_id"), table_name="agent_images")
    op.drop_table("agent_images")
    op.drop_column("mcp_servers", "image_revision")
    op.drop_column("agents", "image_revision")
