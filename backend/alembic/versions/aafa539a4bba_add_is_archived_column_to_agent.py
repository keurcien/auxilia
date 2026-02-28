"""add_is_archived_column_to_agent

Revision ID: aafa539a4bba
Revises: f7e8d9c0b1a2
Create Date: 2026-02-20 16:40:35.903978

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aafa539a4bba'
down_revision: Union[str, Sequence[str], None] = 'f7e8d9c0b1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("agents", "is_archived")
