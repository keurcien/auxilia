"""add oauth_accounts and rename user columns

Revision ID: e75ab54f0585
Revises: 5e352222f637
Create Date: 2026-01-15 16:08:09.556119

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e75ab54f0585'
down_revision: Union[str, Sequence[str], None] = '5e352222f637'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create oauth_accounts table
    op.create_table(
        'oauth_accounts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('sub_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.UniqueConstraint('provider', 'sub_id'),
    )
    op.create_index('ix_oauth_accounts_provider', 'oauth_accounts', ['provider'])
    op.create_index('ix_oauth_accounts_sub_id', 'oauth_accounts', ['sub_id'])

    # Rename columns in users table
    op.alter_column('users', 'password_hash', new_column_name='hashed_password')
    op.alter_column('users', 'is_admin', new_column_name='is_superuser')


def downgrade() -> None:
    """Downgrade schema."""
    # Revert column renames
    op.alter_column('users', 'hashed_password', new_column_name='password_hash')
    op.alter_column('users', 'is_superuser', new_column_name='is_admin')

    # Drop oauth_accounts table
    op.drop_index('ix_oauth_accounts_sub_id', table_name='oauth_accounts')
    op.drop_index('ix_oauth_accounts_provider', table_name='oauth_accounts')
    op.drop_table('oauth_accounts')
