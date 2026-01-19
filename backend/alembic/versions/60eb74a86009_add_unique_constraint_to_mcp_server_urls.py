"""add unique constraint to mcp server urls

Revision ID: 60eb74a86009
Revises: ee903a5e6aa0
Create Date: 2025-12-19 11:22:09.485127

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60eb74a86009'
down_revision: Union[str, Sequence[str], None] = 'ee903a5e6aa0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add unique constraint to mcp_servers.url
    op.create_unique_constraint('uq_mcp_servers_url', 'mcp_servers', ['url'])

    # Add unique constraint to official_mcp_servers.url
    op.create_unique_constraint('uq_official_mcp_servers_url', 'official_mcp_servers', ['url'])


def downgrade() -> None:
    """Downgrade schema."""
    # Remove unique constraint from official_mcp_servers.url
    op.drop_constraint('uq_official_mcp_servers_url', 'official_mcp_servers', type_='unique')

    # Remove unique constraint from mcp_servers.url
    op.drop_constraint('uq_mcp_servers_url', 'mcp_servers', type_='unique')
