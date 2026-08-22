"""add sandboxes table

Revision ID: 3e9d41c7a802
Revises: 1d60a5dabb57
Create Date: 2026-08-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '3e9d41c7a802'
down_revision: Union[str, Sequence[str], None] = '1d60a5dabb57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sandboxes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "provider",
            sa.Enum(
                "opensandbox",
                "cloudrun",
                "daytona",
                name="sandboxprovidertype",
            ),
            nullable=False,
        ),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("encrypted_secret", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("sandboxes")
    sa.Enum(name="sandboxprovidertype").drop(op.get_bind(), checkfirst=True)
