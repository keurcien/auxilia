"""rename PermissionLevel enum value 'user' to 'member'

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-22 10:03:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres 10+ supports renaming an enum value in place; existing rows
    # referencing the old value are updated automatically.
    op.execute("ALTER TYPE permissionlevel RENAME VALUE 'user' TO 'member'")


def downgrade() -> None:
    op.execute("ALTER TYPE permissionlevel RENAME VALUE 'member' TO 'user'")
