"""replace_is_superuser_with_role

Revision ID: a1f2b3c4d5e6
Revises: e33c42c8ef4f
Create Date: 2026-02-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1f2b3c4d5e6"
down_revision: Union[str, None] = "e33c42c8ef4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(10), server_default="member", nullable=False),
    )
    op.execute("UPDATE users SET role = 'admin' WHERE is_superuser = true")
    op.drop_column("users", "is_superuser")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_superuser", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute("UPDATE users SET is_superuser = true WHERE role = 'admin'")
    op.drop_column("users", "role")
