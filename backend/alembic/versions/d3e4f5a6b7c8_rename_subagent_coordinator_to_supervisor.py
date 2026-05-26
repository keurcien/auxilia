"""rename agent_subagents.coordinator_id to supervisor_id

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-22 10:02:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'agent_subagents', 'coordinator_id', new_column_name='supervisor_id'
    )
    op.execute(
        'ALTER INDEX ix_agent_subagents_coordinator_id '
        'RENAME TO ix_agent_subagents_supervisor_id'
    )
    op.execute(
        'ALTER INDEX ix_agent_subagents_coordinator_subagent '
        'RENAME TO ix_agent_subagents_supervisor_subagent'
    )


def downgrade() -> None:
    op.execute(
        'ALTER INDEX ix_agent_subagents_supervisor_subagent '
        'RENAME TO ix_agent_subagents_coordinator_subagent'
    )
    op.execute(
        'ALTER INDEX ix_agent_subagents_supervisor_id '
        'RENAME TO ix_agent_subagents_coordinator_id'
    )
    op.alter_column(
        'agent_subagents', 'supervisor_id', new_column_name='coordinator_id'
    )
