"""add MCP service credentials

Revision ID: e8a1c3f5b7d9
Revises: c7f4a2d9e6b1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "e8a1c3f5b7d9"
down_revision: str | Sequence[str] | None = "c7f4a2d9e6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE mcp_auth_type ADD VALUE IF NOT EXISTS 'service_identity'")
    op.create_table(
        "mcp_server_service_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("principal", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_servers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mcp_server_id"),
    )


def downgrade() -> None:
    op.drop_table("mcp_server_service_credentials")
    op.execute(
        "UPDATE mcp_servers SET auth_type = 'none' WHERE auth_type = 'service_identity'"
    )
    op.execute(
        "ALTER TABLE mcp_servers ALTER COLUMN auth_type TYPE text USING auth_type::text"
    )
    op.execute("DROP TYPE mcp_auth_type")
    op.execute("CREATE TYPE mcp_auth_type AS ENUM ('none', 'api_key', 'oauth2')")
    op.execute(
        "ALTER TABLE mcp_servers ALTER COLUMN auth_type TYPE mcp_auth_type "
        "USING auth_type::mcp_auth_type"
    )
