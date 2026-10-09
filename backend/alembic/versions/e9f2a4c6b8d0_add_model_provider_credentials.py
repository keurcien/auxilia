"""add model provider credentials

Revision ID: e9f2a4c6b8d0
Revises: d7a1b3c5e8f0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "e9f2a4c6b8d0"
down_revision: str | Sequence[str] | None = "d7a1b3c5e8f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_provider_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_provider_credentials_provider",
        "model_provider_credentials",
        ["provider"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_provider_credentials_provider",
        table_name="model_provider_credentials",
    )
    op.drop_table("model_provider_credentials")
