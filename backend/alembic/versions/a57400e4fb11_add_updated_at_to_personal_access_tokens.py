"""Add updated_at to personal_access_tokens

Revision ID: a57400e4fb11
Revises: 150d3bd147c0
Create Date: 2026-04-10 12:22:36.336707

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a57400e4fb11'
down_revision: Union[str, Sequence[str], None] = '150d3bd147c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'personal_access_tokens',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('personal_access_tokens', 'updated_at')
