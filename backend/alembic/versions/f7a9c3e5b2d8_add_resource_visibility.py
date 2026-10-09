"""add resource visibility

Revision ID: f7a9c3e5b2d8
Revises: e6f8a2c4d1b7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "f7a9c3e5b2d8"
down_revision: str | Sequence[str] | None = "e6f8a2c4d1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _team_table(name: str, resource: str, fk: str, unique_name: str) -> None:
    op.create_table(
        name,
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
        sa.Column(fk, sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint([fk], [f"{resource}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(fk, "team_id", name=unique_name),
    )
    op.create_index(op.f(f"ix_{name}_{fk}"), name, [fk], unique=False)
    op.create_index(op.f(f"ix_{name}_team_id"), name, ["team_id"], unique=False)


def upgrade() -> None:
    # A workspace can be left with no memberships after its final user is
    # removed. A standalone MCP server in such a workspace has no meaningful
    # owner candidate; assigning an arbitrary global user would create a
    # cross-workspace ownership edge and an unrelated ON DELETE dependency.
    op.execute(
        """
        DELETE FROM mcp_servers AS server
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_memberships AS membership
            WHERE membership.workspace_id = server.workspace_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM agents AS agent
            WHERE agent.workspace_id = server.workspace_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM skills AS skill
            WHERE skill.workspace_id = server.workspace_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM triggers AS trigger
            WHERE trigger.workspace_id = server.workspace_id
        )
        """
    )
    op.add_column(
        "mcp_servers", sa.Column("owner_id", sa.Uuid(), nullable=True)
    )
    op.create_index(
        op.f("ix_mcp_servers_owner_id"), "mcp_servers", ["owner_id"], unique=False
    )
    op.execute(
        """
        UPDATE mcp_servers AS server
        SET owner_id = COALESCE(
            (
                SELECT membership.user_id
                FROM workspace_memberships AS membership
                WHERE membership.workspace_id = server.workspace_id
                ORDER BY
                    CASE WHEN membership.role = 'admin' THEN 0 ELSE 1 END,
                    membership.created_at,
                    membership.user_id
                LIMIT 1
            ),
            (
                SELECT agent.owner_id
                FROM agents AS agent
                WHERE agent.workspace_id = server.workspace_id
                ORDER BY agent.created_at, agent.id
                LIMIT 1
            ),
            (
                SELECT skill.owner_id
                FROM skills AS skill
                WHERE skill.workspace_id = server.workspace_id
                ORDER BY skill.created_at, skill.id
                LIMIT 1
            ),
            (
                SELECT trigger.owner_id
                FROM triggers AS trigger
                WHERE trigger.workspace_id = server.workspace_id
                ORDER BY trigger.created_at, trigger.id
                LIMIT 1
            )
        )
        """
    )
    op.alter_column("mcp_servers", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_mcp_servers_owner_id_users",
        "mcp_servers",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )

    for table, default in (
        ("mcp_servers", "workspace"),
        ("skills", "workspace"),
        ("triggers", "personal"),
    ):
        op.add_column(
            table,
            sa.Column(
                "visibility",
                sa.String(length=9),
                server_default=default,
                nullable=False,
            ),
        )

    op.add_column(
        "agents",
        sa.Column(
            "visibility",
            sa.String(length=9),
            server_default="personal",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE agents
        SET visibility = 'teams'
        WHERE EXISTS (
            SELECT 1 FROM agent_teams
            WHERE agent_teams.agent_id = agents.id
        )
        """
    )
    # Old links predate audience enclosure. Remove only links whose newly
    # derived scopes are incompatible; otherwise a private subagent could keep
    # executing through a supervisor that exposes it to a broader audience.
    op.execute(
        """
        DELETE FROM agent_subagents AS link
        WHERE NOT EXISTS (
            SELECT 1
            FROM agents AS supervisor
            JOIN agents AS subagent ON subagent.id = link.subagent_id
            WHERE supervisor.id = link.supervisor_id
            AND (
                (
                    supervisor.visibility = 'workspace'
                    AND subagent.visibility = 'workspace'
                )
                OR (
                    supervisor.visibility = 'teams'
                    AND subagent.visibility = 'workspace'
                )
                OR (
                    supervisor.visibility = 'teams'
                    AND subagent.visibility = 'teams'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM agent_teams AS supervisor_team
                        WHERE supervisor_team.agent_id = supervisor.id
                        AND NOT EXISTS (
                            SELECT 1
                            FROM agent_teams AS subagent_team
                            WHERE subagent_team.agent_id = subagent.id
                            AND subagent_team.team_id = supervisor_team.team_id
                        )
                    )
                )
                OR (
                    supervisor.visibility = 'personal'
                    AND subagent.visibility = 'workspace'
                )
                OR (
                    supervisor.visibility = 'personal'
                    AND subagent.visibility = 'personal'
                    AND supervisor.owner_id = subagent.owner_id
                )
            )
        )
        """
    )

    _team_table(
        "mcp_server_teams",
        "mcp_servers",
        "mcp_server_id",
        "uq_mcp_server_visibility_team",
    )
    _team_table("skill_teams", "skills", "skill_id", "uq_skill_visibility_team")
    _team_table(
        "trigger_teams", "triggers", "trigger_id", "uq_trigger_visibility_team"
    )


def downgrade() -> None:
    for name, fk in (
        ("trigger_teams", "trigger_id"),
        ("skill_teams", "skill_id"),
        ("mcp_server_teams", "mcp_server_id"),
    ):
        op.drop_index(op.f(f"ix_{name}_team_id"), table_name=name)
        op.drop_index(op.f(f"ix_{name}_{fk}"), table_name=name)
        op.drop_table(name)

    op.drop_column("agents", "visibility")
    op.drop_column("triggers", "visibility")
    op.drop_column("skills", "visibility")
    op.drop_column("mcp_servers", "visibility")
    op.drop_constraint(
        "fk_mcp_servers_owner_id_users", "mcp_servers", type_="foreignkey"
    )
    op.drop_index(op.f("ix_mcp_servers_owner_id"), table_name="mcp_servers")
    op.drop_column("mcp_servers", "owner_id")
