"""add instance owner

Revision ID: c7e2a4f6b8d1
Revises: b2d5f7a9c1e3
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "c7e2a4f6b8d1"
down_revision: str | Sequence[str] | None = "b2d5f7a9c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_instance_owner",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE users
        SET is_instance_owner = true,
            can_create_workspace = true
        WHERE id = (
            SELECT id
            FROM users
            ORDER BY created_at, id
            LIMIT 1
        )
        """
    )
    op.create_index(
        "uq_users_instance_owner",
        "users",
        ["is_instance_owner"],
        unique=True,
        postgresql_where=sa.text("is_instance_owner"),
    )
    op.create_check_constraint(
        "ck_users_instance_owner_can_create_workspace",
        "users",
        "NOT is_instance_owner OR can_create_workspace",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_instance_owner_can_create_workspace",
        "users",
        type_="check",
    )
    op.drop_index("uq_users_instance_owner", table_name="users")
    op.drop_column("users", "is_instance_owner")
