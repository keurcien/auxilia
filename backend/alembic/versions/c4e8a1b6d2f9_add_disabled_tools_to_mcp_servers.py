"""add disabled tools to MCP servers

Revision ID: c4e8a1b6d2f9
Revises: f5c7a9d1e3b6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "c4e8a1b6d2f9"
down_revision: str | Sequence[str] | None = "f5c7a9d1e3b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "disabled_tools",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "disabled_tools")
