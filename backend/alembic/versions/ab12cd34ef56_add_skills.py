"""Versioned skills, attachments, draft tests and run snapshots.

Revision ID: ab12cd34ef56
Revises: b7e2f4a9c1d3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "ab12cd34ef56"
down_revision = "b7e2f4a9c1d3"
branch_labels = None
depends_on = None


def base():
    return [sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table("skills", *base(), sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("visibility", sa.String(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("draft", postgresql.JSONB(), nullable=False))
    op.create_index("ix_skills_owner_id", "skills", ["owner_id"])
    op.create_table("skill_versions", *base(), sa.Column("skill_id", sa.Uuid(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False), sa.Column("number", sa.Integer(), nullable=False), sa.Column("bundle", postgresql.JSONB(), nullable=False), sa.UniqueConstraint("skill_id", "number"))
    op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])
    op.create_table("agent_skills", *base(), sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False), sa.Column("skill_id", sa.Uuid(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False), sa.Column("version_id", sa.Uuid(), sa.ForeignKey("skill_versions.id", ondelete="RESTRICT"), nullable=False), sa.UniqueConstraint("agent_id", "skill_id"))
    for col in ("agent_id", "skill_id"):
        op.create_index("ix_agent_skills_" + col, "agent_skills", [col])
    op.create_table("skill_tests", *base(), sa.Column("skill_id", sa.Uuid(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False), sa.Column("thread_id", sa.String(), sa.ForeignKey("threads.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("bundle", postgresql.JSONB(), nullable=False), sa.Column("result", sa.String()), sa.Column("notes", sa.String(), nullable=False))
    op.create_index("ix_skill_tests_skill_id", "skill_tests", ["skill_id"])
    op.add_column("runs", sa.Column("skill_snapshot", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("runs", "skill_snapshot")
    for table in ("skill_tests", "agent_skills", "skill_versions", "skills"):
        op.drop_table(table)
