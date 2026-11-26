"""add per-server image preview sources for the chat gallery

Revision ID: a2r4t6v8x0z3
Revises: z1q3s5u7w9y2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "a2r4t6v8x0z3"
down_revision: str | Sequence[str] | None = "z1q3s5u7w9y2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_server_image_previews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.Column("url_template", sa.String(length=2048), nullable=False),
        sa.Column("header_name", sa.String(length=255), nullable=True),
        sa.Column("header_value_encrypted", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_servers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mcp_server_id"),
    )


def downgrade() -> None:
    op.drop_table("mcp_server_image_previews")
