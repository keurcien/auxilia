"""add personal (per-user) API-key and custom HTTP MCP credentials

Revision ID: z1q3s5u7w9y2
Revises: y0p2r4t6v8x1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "z1q3s5u7w9y2"
down_revision: str | Sequence[str] | None = "y0p2r4t6v8x1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "credential_scope",
            sa.String(),
            server_default="shared",
            nullable=False,
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column(
            "personal_header_names",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE mcp_servers SET credential_scope = 'personal' "
        "WHERE auth_type = 'oauth2'"
    )
    op.create_table(
        "mcp_server_user_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mcp_server_id", "user_id", name="uq_mcp_server_user_credential"
        ),
    )
    op.create_index(
        "ix_mcp_server_user_credentials_mcp_server_id",
        "mcp_server_user_credentials",
        ["mcp_server_id"],
    )
    op.create_index(
        "ix_mcp_server_user_credentials_user_id",
        "mcp_server_user_credentials",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_server_user_credentials_user_id",
        table_name="mcp_server_user_credentials",
    )
    op.drop_index(
        "ix_mcp_server_user_credentials_mcp_server_id",
        table_name="mcp_server_user_credentials",
    )
    op.drop_table("mcp_server_user_credentials")
    # Personal API-key and custom HTTP servers become shared servers with no
    # stored secret: connecting fails loudly until an admin sets one.
    op.drop_column("mcp_servers", "personal_header_names")
    op.drop_column("mcp_servers", "credential_scope")
