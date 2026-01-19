"""create_agents_table

Revision ID: e3b81561b671
Revises: 528738f226c2
Create Date: 2025-12-03 17:16:32.795473

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3b81561b671'
down_revision: Union[str, Sequence[str], None] = '528738f226c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'agents',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('avatar_blob', sa.LargeBinary(), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name='agents_owner_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='agent_pkey')
    )
    op.create_index('ix_agents_owner_id', 'agents', ['owner_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_agents_owner_id', table_name='agents')
    op.drop_table('agents')
