"""add project context and skills

Revision ID: c2d4e6f8a0b3
Revises: f1b3d5e7a9c2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "c2d4e6f8a0b3"
down_revision: str | Sequence[str] | None = "f1b3d5e7a9c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "system_prompt",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )

    op.create_table(
        "project_context_files",
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
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "path",
            name="uq_project_context_file_path",
        ),
    )
    op.create_index(
        "ix_project_context_files_project_id",
        "project_context_files",
        ["project_id"],
    )

    op.create_table(
        "project_skills",
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
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "skill_id"),
    )
    op.create_index("ix_project_skills_skill_id", "project_skills", ["skill_id"])


def downgrade() -> None:
    op.drop_table("project_skills")
    op.drop_table("project_context_files")
    op.drop_column("projects", "revision")
    op.drop_column("projects", "system_prompt")
