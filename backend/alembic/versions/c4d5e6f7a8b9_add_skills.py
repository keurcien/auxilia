"""add skills

Revision ID: c4d5e6f7a8b9
Revises: b7e2f4a9c1d3
Create Date: 2026-09-09 00:00:00.000000

Skills: a `skills` table (one SKILL.md plus files per row, owned by a user),
`agent_skills` (which agents have a skill enabled), and two thread columns
for the runtime — the sandbox a thread's runs reconnect to, and the skill
set its current turn runs with.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b7e2f4a9c1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_skills_owner_id"), "skills", ["owner_id"], unique=False)
    op.create_index(op.f("ix_skills_name"), "skills", ["name"], unique=False)

    op.create_table(
        "agent_skills",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "skill_id"),
    )
    op.create_index(
        op.f("ix_agent_skills_skill_id"), "agent_skills", ["skill_id"], unique=False
    )

    op.add_column("threads", sa.Column("sandbox_id", sa.String(), nullable=True))
    op.add_column(
        "threads", sa.Column("skill_snapshot", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("threads", "skill_snapshot")
    op.drop_column("threads", "sandbox_id")
    op.drop_index(op.f("ix_agent_skills_skill_id"), table_name="agent_skills")
    op.drop_table("agent_skills")
    op.drop_index(op.f("ix_skills_name"), table_name="skills")
    op.drop_index(op.f("ix_skills_owner_id"), table_name="skills")
    op.drop_table("skills")
