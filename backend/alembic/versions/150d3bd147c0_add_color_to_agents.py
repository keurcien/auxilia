"""add color to agents

Revision ID: 150d3bd147c0
Revises: e44a6b57e444
Create Date: 2026-04-04 23:34:16.351658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '150d3bd147c0'
down_revision: Union[str, Sequence[str], None] = 'e44a6b57e444'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agents', sa.Column('color', sa.String(length=7), nullable=True))
    op.execute("UPDATE agents SET color = '#9E9E9E' WHERE color IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agents', 'color')
