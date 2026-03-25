"""create_agent_subagent_bindings_table

Revision ID: a7c3e9f2b1d4
Revises: b4a7e2f1c9d3
Create Date: 2026-03-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9f2b1d4'
down_revision: Union[str, Sequence[str], None] = 'b4a7e2f1c9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'agent_subagent_bindings',
        sa.Column('coordinator_id', sa.Uuid(), nullable=False),
        sa.Column('subagent_id', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['coordinator_id'], ['agents.id']),
        sa.ForeignKeyConstraint(['subagent_id'], ['agents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_agent_subagent_bindings_coordinator_id',
        'agent_subagent_bindings',
        ['coordinator_id'],
    )
    op.create_index(
        'ix_agent_subagent_bindings_subagent_id',
        'agent_subagent_bindings',
        ['subagent_id'],
    )
    op.create_index(
        'ix_agent_subagent_bindings_coordinator_subagent',
        'agent_subagent_bindings',
        ['coordinator_id', 'subagent_id'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_agent_subagent_bindings_coordinator_subagent', table_name='agent_subagent_bindings')
    op.drop_index('ix_agent_subagent_bindings_subagent_id', table_name='agent_subagent_bindings')
    op.drop_index('ix_agent_subagent_bindings_coordinator_id', table_name='agent_subagent_bindings')
    op.drop_table('agent_subagent_bindings')
