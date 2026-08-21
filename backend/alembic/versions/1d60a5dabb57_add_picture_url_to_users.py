"""add picture_url to users

Revision ID: 1d60a5dabb57
Revises: d7b3f1c05a92
Create Date: 2026-08-21 15:51:13.278817

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1d60a5dabb57'
down_revision: Union[str, Sequence[str], None] = 'd7b3f1c05a92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('picture_url', sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'picture_url')
