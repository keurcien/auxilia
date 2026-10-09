"""add Slack thread mention setting

Revision ID: b9e3d5f7a1c4
Revises: a8d2c4e6f0b1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "b9e3d5f7a1c4"
down_revision: str | Sequence[str] | None = "a8d2c4e6f0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_slack_bots",
        sa.Column(
            "require_mention_in_threads",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_slack_bots", "require_mention_in_threads")
