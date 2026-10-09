"""allow duplicate MCP server URLs

Revision ID: f9b2d4e6a8c0
Revises: e8a1c3f5b7d9
"""

from collections.abc import Sequence

from alembic import op


revision: str = "f9b2d4e6a8c0"
down_revision: str | Sequence[str] | None = "e8a1c3f5b7d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_mcp_server_workspace_url",
        "mcp_servers",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_mcp_server_workspace_url",
        "mcp_servers",
        ["workspace_id", "url"],
    )
