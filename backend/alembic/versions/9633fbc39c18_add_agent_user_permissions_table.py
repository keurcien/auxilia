"""add agent_user_permissions table

Revision ID: 9633fbc39c18
Revises: f7e8d9c0b1a2
Create Date: 2026-02-16 00:49:16.286994

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9633fbc39c18'
down_revision: Union[str, Sequence[str], None] = 'f7e8d9c0b1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('agent_user_permissions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('permission', sa.Enum('user', 'editor', 'admin', name='permissionlevel'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'user_id', name='uq_agent_user_permission')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('agent_user_permissions')
    op.execute("DROP TYPE IF EXISTS permissionlevel")
