"""create_personal_access_tokens_table

Revision ID: 0ea6423f4df4
Revises: 3902b1f0b15e
Create Date: 2026-03-09 19:05:22.548057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision: str = '0ea6423f4df4'
down_revision: Union[str, Sequence[str], None] = '3902b1f0b15e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('personal_access_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('token_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('prefix', sqlmodel.sql.sqltypes.AutoString(length=12), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_personal_access_tokens_prefix'), 'personal_access_tokens', ['prefix'], unique=False)
    op.create_index(op.f('ix_personal_access_tokens_user_id'), 'personal_access_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_personal_access_tokens_user_id'), table_name='personal_access_tokens')
    op.drop_index(op.f('ix_personal_access_tokens_prefix'), table_name='personal_access_tokens')
    op.drop_table('personal_access_tokens')
