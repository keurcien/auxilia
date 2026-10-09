"""add Slack tool callout setting

Revision ID: c7f4a2d9e6b1
Revises: b9e3d5f7a1c4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "c7f4a2d9e6b1"
down_revision: str | Sequence[str] | None = "b9e3d5f7a1c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_slack_bots",
        sa.Column(
            "show_tool_callouts",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_slack_bots", "show_tool_callouts")
