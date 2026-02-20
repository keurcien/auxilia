"""add_slack_official_mcp_server

Revision ID: e33c42c8ef4f
Revises: ef73e181d878
Create Date: 2026-02-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e33c42c8ef4f'
down_revision: Union[str, Sequence[str], None] = 'ef73e181d878'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO official_mcp_servers (name, url, auth_type, icon_url, description, supports_dcr)
            VALUES (
                'Slack',
                'https://mcp.slack.com/mcp',
                'oauth2',
                'https://storage.googleapis.com/choose-assets/slack.png',
                'The Slack MCP server provides tools for searching through Slack, retrieving and sending messages, managing canvases, and managing users. Each of these tools provides useful functionality for interacting with Slack; combine them for comprehensive integrations that grasp your team''s context and history.',
                false
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM official_mcp_servers WHERE name = 'Slack' AND url = 'https://mcp.slack.com/mcp'
            """
        )
    )
