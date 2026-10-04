"""cascade agent binding fks

Revision ID: d8f3b5c7e9a2
Revises: c7e2a4f6b8d1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "d8f3b5c7e9a2"
down_revision: str | Sequence[str] | None = "c7e2a4f6b8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Binding rows owned by an agent. Without a cascade, deleting a workspace
# (which cascades to its agents) is refused as soon as one agent has an MCP
# binding, a permission grant or a subagent link — these tables carry no
# workspace_id, so nothing else removes them.
BINDINGS: list[tuple[str, str]] = [
    ("agent_mcp_servers", "agent_id"),
    ("agent_user_permissions", "agent_id"),
    ("agent_subagents", "supervisor_id"),
    ("agent_subagents", "subagent_id"),
]


def _fk_name(table: str, column: str) -> str:
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if fk["referred_table"] == "agents" and fk["constrained_columns"] == [column]:
            name = fk["name"]
            if name is None:
                break
            return name
    raise RuntimeError(f"No foreign key found for {table}.{column} -> agents")


def _recreate(table: str, column: str, *, ondelete: str | None) -> None:
    op.drop_constraint(_fk_name(table, column), table, type_="foreignkey")
    op.create_foreign_key(
        f"{table}_{column}_fkey",
        table,
        "agents",
        [column],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    for table, column in BINDINGS:
        _recreate(table, column, ondelete="CASCADE")


def downgrade() -> None:
    for table, column in BINDINGS:
        _recreate(table, column, ondelete=None)
