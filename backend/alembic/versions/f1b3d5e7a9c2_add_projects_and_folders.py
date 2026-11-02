"""add projects and folders

Revision ID: f1b3d5e7a9c2
Revises: e096d15afe41
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "f1b3d5e7a9c2"
down_revision: str | Sequence[str] | None = "e096d15afe41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
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
        sa.Column("id", sa.Uuid(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "projects",
        *_base_columns(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "visibility",
            sa.String(length=9),
            server_default="personal",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])

    op.create_table(
        "project_teams",
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
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "team_id"),
    )
    op.create_index("ix_project_teams_team_id", "project_teams", ["team_id"])

    op.create_table(
        "project_folders",
        *_base_columns(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["project_folders.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "parent_id",
            "name",
            name="uq_project_folder_sibling_name",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_project_folders_parent_id", "project_folders", ["parent_id"])
    op.create_index("ix_project_folders_project_id", "project_folders", ["project_id"])

    for table in ("threads", "triggers"):
        op.add_column(table, sa.Column("project_id", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("folder_id", sa.Uuid(), nullable=True))
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
        op.create_index(f"ix_{table}_folder_id", table, ["folder_id"])
        op.create_foreign_key(
            f"fk_{table}_project_id_projects",
            table,
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{table}_folder_id_project_folders",
            table,
            "project_folders",
            ["folder_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column(
        "threads",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("threads", "completed_at")
    for table in ("triggers", "threads"):
        op.drop_constraint(
            f"fk_{table}_folder_id_project_folders", table, type_="foreignkey"
        )
        op.drop_constraint(f"fk_{table}_project_id_projects", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_folder_id", table_name=table)
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.drop_column(table, "folder_id")
        op.drop_column(table, "project_id")
    op.drop_table("project_folders")
    op.drop_table("project_teams")
    op.drop_table("projects")
