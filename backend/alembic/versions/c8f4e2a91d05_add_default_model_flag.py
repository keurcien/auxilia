"""add default model flag

Revision ID: c8f4e2a91d05
Revises: 77853f24b2ed
Create Date: 2026-07-22 10:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f4e2a91d05'
down_revision: Union[str, Sequence[str], None] = '77853f24b2ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Starts unset everywhere: no seed — consumers fall back to the first
    # available model until an admin flags one.
    op.add_column(
        "models",
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    # Partial unique index: at most one default row, any number of non-defaults.
    op.create_index(
        "uq_models_single_default",
        "models",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_models_single_default", table_name="models")
    op.drop_column("models", "is_default")
