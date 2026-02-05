"""remove_enabled_tools_column

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-02-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove enabled_tools column from agent_mcp_server_bindings table."""
    op.drop_column('agent_mcp_server_bindings', 'enabled_tools')


def downgrade() -> None:
    """Re-add enabled_tools column to agent_mcp_server_bindings table."""
    op.add_column(
        'agent_mcp_server_bindings',
        sa.Column('enabled_tools', sa.ARRAY(sa.String()), nullable=True)
    )
