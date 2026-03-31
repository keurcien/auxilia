"""rename_binding_tables_to_simplified_names

Revision ID: d5e6f7a8b9c0
Revises: a7c3e9f2b1d4
Create Date: 2026-03-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9f2b1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename association tables and their indexes/constraints."""
    # --- agent_mcp_server_bindings → agent_mcp_servers ---
    op.rename_table('agent_mcp_server_bindings', 'agent_mcp_servers')
    op.execute('ALTER INDEX ix_agent_mcp_server_bindings_agent_id RENAME TO ix_agent_mcp_servers_agent_id')
    op.execute('ALTER INDEX ix_agent_mcp_server_bindings_agent_server RENAME TO ix_agent_mcp_servers_agent_server')

    # --- agent_subagent_bindings → agent_subagents ---
    op.rename_table('agent_subagent_bindings', 'agent_subagents')
    op.execute('ALTER INDEX ix_agent_subagent_bindings_coordinator_id RENAME TO ix_agent_subagents_coordinator_id')
    op.execute('ALTER INDEX ix_agent_subagent_bindings_subagent_id RENAME TO ix_agent_subagents_subagent_id')
    op.execute('ALTER INDEX ix_agent_subagent_bindings_coordinator_subagent RENAME TO ix_agent_subagents_coordinator_subagent')


def downgrade() -> None:
    """Reverse all renames."""
    # --- agent_subagents → agent_subagent_bindings ---
    op.execute('ALTER INDEX ix_agent_subagents_coordinator_subagent RENAME TO ix_agent_subagent_bindings_coordinator_subagent')
    op.execute('ALTER INDEX ix_agent_subagents_subagent_id RENAME TO ix_agent_subagent_bindings_subagent_id')
    op.execute('ALTER INDEX ix_agent_subagents_coordinator_id RENAME TO ix_agent_subagent_bindings_coordinator_id')
    op.rename_table('agent_subagents', 'agent_subagent_bindings')

    # --- agent_mcp_servers → agent_mcp_server_bindings ---
    op.execute('ALTER INDEX ix_agent_mcp_servers_agent_server RENAME TO ix_agent_mcp_server_bindings_agent_server')
    op.execute('ALTER INDEX ix_agent_mcp_servers_agent_id RENAME TO ix_agent_mcp_server_bindings_agent_id')
    op.rename_table('agent_mcp_servers', 'agent_mcp_server_bindings')
