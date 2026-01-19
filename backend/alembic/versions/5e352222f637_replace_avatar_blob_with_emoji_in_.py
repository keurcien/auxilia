"""replace_avatar_blob_with_emoji_in_agents_table

Revision ID: 5e352222f637
Revises: 60eb74a86009
Create Date: 2025-12-19 17:03:52.300132

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e352222f637'
down_revision: Union[str, Sequence[str], None] = '60eb74a86009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Remove avatar_blob column
    op.drop_column('agents', 'avatar_blob')
    # Add emoji column
    op.add_column('agents', sa.Column('emoji', sa.String(length=10), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove emoji column
    op.drop_column('agents', 'emoji')
    # Add back avatar_blob column
    op.add_column('agents', sa.Column('avatar_blob', sa.LargeBinary(), nullable=True))
