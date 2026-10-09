"""make appearance instance global

Revision ID: a1c4e6f8b0d2
Revises: f0b3d5e7a9c2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "a1c4e6f8b0d2"
down_revision: str | Sequence[str] | None = "f0b3d5e7a9c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Appearance used to have one row per workspace. The last edited value is
    # the best representation of the instance-wide branding when consolidating.
    op.execute(
        """
        DELETE FROM workspace_appearance
        WHERE id NOT IN (
            SELECT id
            FROM workspace_appearance
            ORDER BY updated_at DESC, created_at DESC, id DESC
            LIMIT 1
        )
        """
    )
    op.drop_constraint(
        "uq_appearance_workspace_key",
        "workspace_appearance",
        type_="unique",
    )
    op.drop_index(
        "ix_workspace_appearance_workspace_id",
        table_name="workspace_appearance",
    )
    op.drop_constraint(
        "fk_workspace_appearance_workspace_id_workspaces",
        "workspace_appearance",
        type_="foreignkey",
    )
    op.drop_column("workspace_appearance", "workspace_id")
    op.rename_table("workspace_appearance", "instance_appearance")
    op.create_unique_constraint(
        "instance_appearance_key_key",
        "instance_appearance",
        ["key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "instance_appearance_key_key",
        "instance_appearance",
        type_="unique",
    )
    op.rename_table("instance_appearance", "workspace_appearance")
    op.add_column(
        "workspace_appearance",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        """
        UPDATE workspace_appearance
        SET workspace_id = (
            SELECT id FROM workspaces ORDER BY created_at, id LIMIT 1
        )
        """
    )
    op.alter_column("workspace_appearance", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_workspace_appearance_workspace_id_workspaces",
        "workspace_appearance",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_workspace_appearance_workspace_id",
        "workspace_appearance",
        ["workspace_id"],
    )
    op.create_unique_constraint(
        "uq_appearance_workspace_key",
        "workspace_appearance",
        ["workspace_id", "key"],
    )
