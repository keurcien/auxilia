"""create_agent_mcp_server_bindings_table

Revision ID: 41256d98e51d
Revises: e3b81561b671
Create Date: 2025-12-03 16:53:44.905013

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41256d98e51d'
down_revision: Union[str, Sequence[str], None] = 'e3b81561b671'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'agent_mcp_server_bindings',
        sa.Column('agent_id', sa.Uuid(), nullable=False),
        sa.Column('mcp_server_id', sa.Uuid(), nullable=False),
        sa.Column('enabled_tools', sa.ARRAY(sa.String()), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['mcp_server_id'], ['mcp_servers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    # Create index for faster lookups by agent_id and agent_id+mcp_server_id
    op.create_index('ix_agent_mcp_server_bindings_agent_id', 'agent_mcp_server_bindings', ['agent_id'])
    op.create_index(
        'ix_agent_mcp_server_bindings_agent_server',
        'agent_mcp_server_bindings',
        ['agent_id', 'mcp_server_id'],
        unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_agent_mcp_server_bindings_agent_server', table_name='agent_mcp_server_bindings')
    op.drop_index('ix_agent_mcp_server_bindings_agent_id', table_name='agent_mcp_server_bindings')
    op.drop_table('agent_mcp_server_bindings')
