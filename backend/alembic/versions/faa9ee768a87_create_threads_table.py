"""create_threads_table

Revision ID: faa9ee768a87
Revises: 41256d98e51d
Create Date: 2025-12-05 14:38:49.018638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'faa9ee768a87'
down_revision: Union[str, Sequence[str], None] = '41256d98e51d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'threads',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('agent_id', sa.Uuid(), nullable=False),
        sa.Column('first_message_content', sa.Text(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    # Create indexes for faster lookups
    op.create_index('ix_threads_user_id', 'threads', ['user_id'])
    op.create_index('ix_threads_agent_id', 'threads', ['agent_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_threads_agent_id', table_name='threads')
    op.drop_index('ix_threads_user_id', table_name='threads')
    op.drop_table('threads')
