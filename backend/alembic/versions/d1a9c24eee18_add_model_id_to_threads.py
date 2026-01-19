"""add_model_id_to_threads

Revision ID: d1a9c24eee18
Revises: faa9ee768a87
Create Date: 2025-12-12 21:44:15.785426

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a9c24eee18'
down_revision: Union[str, Sequence[str], None] = 'faa9ee768a87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('threads', sa.Column('model_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('threads', 'model_id')
