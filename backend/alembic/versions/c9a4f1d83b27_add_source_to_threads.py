"""Add source column to threads

Revision ID: c9a4f1d83b27
Revises: a57400e4fb11
Create Date: 2026-05-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9a4f1d83b27'
down_revision: Union[str, Sequence[str], None] = 'a57400e4fb11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'threads',
        sa.Column('source', sa.String(), nullable=True),
    )
    # Slack threads historically used the Slack thread_ts (contains '.') as id;
    # everything else was created via the in-app web UI.
    op.execute("UPDATE threads SET source = 'slack' WHERE id LIKE '%.%'")
    op.execute("UPDATE threads SET source = 'web' WHERE source IS NULL")
    op.alter_column(
        'threads',
        'source',
        existing_type=sa.String(),
        nullable=False,
        server_default='web',
    )


def downgrade() -> None:
    op.drop_column('threads', 'source')
