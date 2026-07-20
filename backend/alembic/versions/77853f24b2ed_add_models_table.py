"""add models table

Revision ID: 77853f24b2ed
Revises: b2c3d4e5f6a7
Create Date: 2026-07-20 15:32:07.532520

"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77853f24b2ed'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The models offered before workspace model management existed (catalog.py's
# hardcoded list at the time of this migration). Seeded as enabled so existing
# workspaces notice nothing; anything added to the whitelist later starts
# disabled until an admin opts in.
SEED_MODELS: list[tuple[str, str]] = [
    ("openai", "gpt-4o-mini"),
    ("deepseek", "deepseek-v4-flash"),
    ("deepseek", "deepseek-v4-pro"),
    ("anthropic", "claude-haiku-4-5"),
    ("anthropic", "claude-sonnet-4-6"),
    ("anthropic", "claude-sonnet-5"),
    ("google", "gemini-3-flash-preview"),
    ("google", "gemini-3-pro-preview"),
    ("xiaomi", "mimo-v2.5-pro"),
    ("xiaomi", "mimo-v2.5"),
    ("meta", "muse-spark-1.1"),
    ("openrouter", "glm-5.2-max"),
    ("openrouter", "glm-5.2-high"),
]


def upgrade() -> None:
    """Upgrade schema."""
    models_table = op.create_table(
        "models",
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
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "model_id"),
    )
    op.bulk_insert(
        models_table,
        [
            {
                "id": uuid4(),
                "provider": provider,
                "model_id": model_id,
                "is_enabled": True,
            }
            for provider, model_id in SEED_MODELS
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("models")
