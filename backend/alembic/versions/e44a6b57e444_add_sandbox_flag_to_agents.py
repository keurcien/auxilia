"""add sandbox flag to agents

Revision ID: e44a6b57e444
Revises: d5e6f7a8b9c0
Create Date: 2026-04-01 09:49:55.751687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e44a6b57e444'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('sandbox', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('agents', 'sandbox')
