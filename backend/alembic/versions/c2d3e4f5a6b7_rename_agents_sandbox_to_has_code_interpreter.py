"""rename agents.sandbox to has_code_interpreter

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-22 10:01:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('agents', 'sandbox', new_column_name='has_code_interpreter')


def downgrade() -> None:
    op.alter_column('agents', 'has_code_interpreter', new_column_name='sandbox')
