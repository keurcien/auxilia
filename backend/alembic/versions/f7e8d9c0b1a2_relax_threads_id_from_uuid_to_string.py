"""relax_threads_id_from_uuid_to_string

Revision ID: f7e8d9c0b1a2
Revises: c3d4e5f6g7h8
Create Date: 2026-02-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f7e8d9c0b1a2'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change threads.id from UUID to String."""
    op.alter_column(
        'threads',
        'id',
        existing_type=sa.Uuid(),
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using='id::text',
    )


def downgrade() -> None:
    """Revert threads.id from String back to UUID."""
    op.alter_column(
        'threads',
        'id',
        existing_type=sa.String(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='id::uuid',
    )
