"""add_description_to_agents

Revision ID: ef73e181d878
Revises: 9633fbc39c18
Create Date: 2026-02-18 10:55:00.923307

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef73e181d878'
down_revision: Union[str, Sequence[str], None] = '9633fbc39c18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agents', sa.Column('description', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agents', 'description')
