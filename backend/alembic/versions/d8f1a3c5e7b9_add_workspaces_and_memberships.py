"""add workspaces and memberships

Revision ID: d8f1a3c5e7b9
Revises: c6e8f0a2b4d7
Create Date: 2026-10-03 06:20:00.000000
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa

from alembic import op


revision: str = "d8f1a3c5e7b9"
down_revision: str | Sequence[str] | None = "c6e8f0a2b4d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    workspace_id = uuid4()

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO workspaces (id, name) "
            "VALUES (:workspace_id, 'Default workspace')"
        ).bindparams(workspace_id=workspace_id)
    )

    op.add_column(
        "users",
        sa.Column(
            "can_create_workspace",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute("UPDATE users SET can_create_workspace = true WHERE role = 'admin'")

    op.add_column("teams", sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text("UPDATE teams SET workspace_id = :workspace_id").bindparams(
            workspace_id=workspace_id
        )
    )
    op.alter_column("teams", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_teams_workspace_id_workspaces",
        "teams",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_teams_name", table_name="teams")
    op.create_index("ix_teams_name", "teams", ["name"], unique=False)
    op.create_index("ix_teams_workspace_id", "teams", ["workspace_id"], unique=False)
    op.create_unique_constraint(
        "uq_team_workspace_name",
        "teams",
        ["workspace_id", "name"],
    )

    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=10),
            server_default="member",
            nullable=False,
        ),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_membership_workspace_user",
        ),
    )
    op.create_index(
        "ix_workspace_memberships_workspace_id",
        "workspace_memberships",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_memberships_user_id",
        "workspace_memberships",
        ["user_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "INSERT INTO workspace_memberships "
            "(id, workspace_id, user_id, role, team_id) "
            "SELECT gen_random_uuid(), :workspace_id, id, role, team_id FROM users"
        ).bindparams(workspace_id=workspace_id)
    )

    op.add_column("invites", sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text("UPDATE invites SET workspace_id = :workspace_id").bindparams(
            workspace_id=workspace_id
        )
    )
    op.alter_column("invites", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_invites_workspace_id_workspaces",
        "invites",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_invites_workspace_id",
        "invites",
        ["workspace_id"],
        unique=False,
    )

    op.add_column(
        "workspace_authentication",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE workspace_authentication SET workspace_id = :workspace_id"
        ).bindparams(workspace_id=workspace_id)
    )
    op.create_foreign_key(
        "fk_workspace_authentication_workspace_id_workspaces",
        "workspace_authentication",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_workspace_authentication_workspace_id",
        "workspace_authentication",
        ["workspace_id"],
        unique=False,
    )
    op.alter_column("workspace_authentication", "workspace_id", nullable=False)
    op.drop_constraint(
        "workspace_authentication_key_key",
        "workspace_authentication",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_workspace_authentication_workspace_key",
        "workspace_authentication",
        ["workspace_id", "key"],
    )

    # Workspace-owned synchronous HTTP resources. Columns are added nullable,
    # backfilled to the compatibility workspace, constrained, then made
    # non-null so upgrades remain safe with existing rows.
    scoped_tables = (
        "agents",
        "mcp_servers",
        "skill_sources",
        "skills",
        "sandboxes",
        "models",
        "model_provider_credentials",
        "workspace_appearance",
        "workspace_observability",
        "slack_notification_settings",
    )
    for table in scoped_tables:
        op.add_column(table, sa.Column("workspace_id", sa.Uuid(), nullable=True))
        scoped_table = sa.table(
            table,
            sa.column("workspace_id", sa.Uuid()),
        )
        op.execute(scoped_table.update().values(workspace_id=workspace_id))
        op.create_foreign_key(
            f"fk_{table}_workspace_id_workspaces",
            table,
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
        op.alter_column(table, "workspace_id", nullable=False)

    op.add_column(
        "slack_notification_settings",
        sa.Column("slack_team_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_slack_notification_settings_slack_team_id",
        "slack_notification_settings",
        ["slack_team_id"],
        unique=True,
    )

    # Durable asynchronous resources. Their public ids stay globally stable,
    # while every lookup and background hand-off is workspace-scoped.
    for table in ("triggers", "threads", "runs"):
        op.add_column(table, sa.Column("workspace_id", sa.Uuid(), nullable=True))
        scoped_table = sa.table(
            table,
            sa.column("workspace_id", sa.Uuid()),
        )
        op.execute(scoped_table.update().values(workspace_id=workspace_id))
        op.create_foreign_key(
            f"fk_{table}_workspace_id_workspaces",
            table,
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
        op.alter_column(table, "workspace_id", nullable=False)

    op.drop_constraint("uq_mcp_servers_url", "mcp_servers", type_="unique")
    op.create_unique_constraint(
        "uq_mcp_server_workspace_url",
        "mcp_servers",
        ["workspace_id", "url"],
    )

    op.drop_index("ix_skills_name", table_name="skills")
    op.create_index("ix_skills_name", "skills", ["name"])
    op.create_unique_constraint(
        "uq_skills_workspace_name", "skills", ["workspace_id", "name"]
    )

    op.execute("DROP INDEX IF EXISTS uq_skill_sources_identity")
    op.execute(
        "CREATE UNIQUE INDEX uq_skill_sources_identity ON skill_sources "
        "(workspace_id, url, ref, coalesce(subpath, ''))"
    )

    op.drop_constraint("models_provider_model_id_key", "models", type_="unique")
    op.create_unique_constraint(
        "uq_models_workspace_provider_model",
        "models",
        ["workspace_id", "provider", "model_id"],
    )
    op.drop_index("uq_models_single_default", table_name="models")
    op.create_index(
        "uq_models_single_default",
        "models",
        ["workspace_id", "is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.drop_index(
        "ix_model_provider_credentials_provider",
        table_name="model_provider_credentials",
    )
    op.create_index(
        "ix_model_provider_credentials_provider",
        "model_provider_credentials",
        ["provider"],
    )
    op.create_unique_constraint(
        "uq_model_credentials_workspace_provider",
        "model_provider_credentials",
        ["workspace_id", "provider"],
    )

    for table, constraint in (
        ("workspace_appearance", "uq_appearance_workspace_key"),
        ("workspace_observability", "uq_observability_workspace_key"),
        ("slack_notification_settings", "uq_slack_notifications_workspace_key"),
    ):
        op.drop_constraint(f"{table}_key_key", table, type_="unique")
        op.create_unique_constraint(constraint, table, ["workspace_id", "key"])

    op.drop_constraint("fk_users_team_id_teams", "users", type_="foreignkey")
    op.drop_column("users", "team_id")
    op.drop_column("users", "role")


def downgrade() -> None:
    for table in reversed(("triggers", "threads", "runs")):
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_constraint(
            f"fk_{table}_workspace_id_workspaces", table, type_="foreignkey"
        )
        op.drop_column(table, "workspace_id")

    op.drop_index(
        "ix_slack_notification_settings_slack_team_id",
        table_name="slack_notification_settings",
    )
    op.drop_column("slack_notification_settings", "slack_team_id")

    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=10),
            server_default="member",
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_users_team_id_teams",
        "users",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "UPDATE users SET role = membership.role, team_id = membership.team_id "
        "FROM workspace_memberships AS membership "
        "WHERE membership.user_id = users.id"
    )

    for table, constraint in (
        ("workspace_appearance", "uq_appearance_workspace_key"),
        ("workspace_observability", "uq_observability_workspace_key"),
        ("slack_notification_settings", "uq_slack_notifications_workspace_key"),
    ):
        op.drop_constraint(constraint, table, type_="unique")
        op.create_unique_constraint(f"{table}_key_key", table, ["key"])

    op.drop_constraint(
        "uq_model_credentials_workspace_provider",
        "model_provider_credentials",
        type_="unique",
    )
    op.drop_index(
        "ix_model_provider_credentials_provider",
        table_name="model_provider_credentials",
    )
    op.create_index(
        "ix_model_provider_credentials_provider",
        "model_provider_credentials",
        ["provider"],
        unique=True,
    )
    op.drop_index("uq_models_single_default", table_name="models")
    op.create_index(
        "uq_models_single_default",
        "models",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.drop_constraint("uq_models_workspace_provider_model", "models", type_="unique")
    op.create_unique_constraint(
        "models_provider_model_id_key", "models", ["provider", "model_id"]
    )
    op.execute("DROP INDEX IF EXISTS uq_skill_sources_identity")
    op.execute(
        "CREATE UNIQUE INDEX uq_skill_sources_identity ON skill_sources "
        "(url, ref, coalesce(subpath, ''))"
    )
    op.drop_constraint("uq_skills_workspace_name", "skills", type_="unique")
    op.drop_index("ix_skills_name", table_name="skills")
    op.create_index("ix_skills_name", "skills", ["name"], unique=True)
    op.drop_constraint("uq_mcp_server_workspace_url", "mcp_servers", type_="unique")
    op.create_unique_constraint("uq_mcp_servers_url", "mcp_servers", ["url"])

    for table in reversed(
        (
            "agents",
            "mcp_servers",
            "skill_sources",
            "skills",
            "sandboxes",
            "models",
            "model_provider_credentials",
            "workspace_appearance",
            "workspace_observability",
            "slack_notification_settings",
        )
    ):
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_constraint(
            f"fk_{table}_workspace_id_workspaces", table, type_="foreignkey"
        )
        op.drop_column(table, "workspace_id")

    op.execute(
        "DELETE FROM workspace_authentication AS candidate "
        "USING workspace_authentication AS keeper "
        "WHERE candidate.key = keeper.key "
        "AND (candidate.created_at, candidate.id) > "
        "(keeper.created_at, keeper.id)"
    )
    op.drop_constraint(
        "uq_workspace_authentication_workspace_key",
        "workspace_authentication",
        type_="unique",
    )
    op.create_unique_constraint(
        "workspace_authentication_key_key",
        "workspace_authentication",
        ["key"],
    )
    op.drop_index(
        "ix_workspace_authentication_workspace_id",
        table_name="workspace_authentication",
    )
    op.drop_constraint(
        "fk_workspace_authentication_workspace_id_workspaces",
        "workspace_authentication",
        type_="foreignkey",
    )
    op.drop_column("workspace_authentication", "workspace_id")

    op.drop_index("ix_invites_workspace_id", table_name="invites")
    op.drop_constraint(
        "fk_invites_workspace_id_workspaces",
        "invites",
        type_="foreignkey",
    )
    op.drop_column("invites", "workspace_id")

    op.drop_index(
        "ix_workspace_memberships_user_id",
        table_name="workspace_memberships",
    )
    op.drop_index(
        "ix_workspace_memberships_workspace_id",
        table_name="workspace_memberships",
    )
    op.drop_table("workspace_memberships")

    op.drop_constraint("uq_team_workspace_name", "teams", type_="unique")
    op.drop_index("ix_teams_workspace_id", table_name="teams")
    op.drop_index("ix_teams_name", table_name="teams")
    op.create_index("ix_teams_name", "teams", ["name"], unique=True)
    op.drop_constraint(
        "fk_teams_workspace_id_workspaces",
        "teams",
        type_="foreignkey",
    )
    op.drop_column("teams", "workspace_id")

    op.drop_column("users", "can_create_workspace")
    op.drop_table("workspaces")
