"""add user profiles and two factor

Revision ID: d7a1b3c5e8f0
Revises: 8c2f4d6a9b10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "d7a1b3c5e8f0"
down_revision: str | Sequence[str] | None = "8c2f4d6a9b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("image_revision", sa.Uuid(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "two_factor_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE users SET first_name = left(name, 100) WHERE name IS NOT NULL"
    )

    op.create_table(
        "user_images",
        *_timestamps(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(50), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_image_user_id"),
    )
    op.create_index(
        op.f("ix_user_images_user_id"),
        "user_images",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "user_two_factors",
        *_timestamps(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret_encrypted", sa.String(), nullable=False),
        sa.Column("backup_code_hashes", sa.JSON(), nullable=False),
        sa.Column("last_used_totp_counter", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_two_factor_user_id"),
    )
    op.create_index(
        op.f("ix_user_two_factors_user_id"),
        "user_two_factors",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_two_factors_user_id"),
        table_name="user_two_factors",
    )
    op.drop_table("user_two_factors")
    op.drop_index(op.f("ix_user_images_user_id"), table_name="user_images")
    op.drop_table("user_images")
    op.drop_column("users", "two_factor_enabled")
    op.drop_column("users", "image_revision")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
