"""rename users.hashed_password to password_hash

Revision ID: b1c2d3e4f5a6
Revises: c9a4f1d83b27
Create Date: 2026-05-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'c9a4f1d83b27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'hashed_password', new_column_name='password_hash')


def downgrade() -> None:
    op.alter_column('users', 'password_hash', new_column_name='hashed_password')
