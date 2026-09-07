"""Replace published skill versions with directly editable bundles.

Revision ID: cd34ef56ab78
Revises: ab12cd34ef56
"""

import sqlalchemy as sa

from alembic import op


revision = "cd34ef56ab78"
down_revision = "ab12cd34ef56"
branch_labels = None
depends_on = None


def upgrade():
    # The last saved content becomes the live skill; preserve every attachment.
    op.alter_column("skills", "draft", new_column_name="bundle")
    op.drop_column("agent_skills", "version_id")
    # Keep the legacy tables as a migration-only backup for downgrade. They are
    # not mapped or read by the application and no new history is written.
    op.rename_table("skill_versions", "legacy_skill_versions")
    op.rename_table("skill_tests", "legacy_skill_tests")


def downgrade():
    op.rename_table("legacy_skill_tests", "skill_tests")
    op.rename_table("legacy_skill_versions", "skill_versions")
    op.add_column("agent_skills", sa.Column("version_id", sa.Uuid(), nullable=True))
    # Give each skill a current published version, including newly created skills.
    op.execute("""
        INSERT INTO skill_versions (id, created_at, updated_at, skill_id, number, bundle)
        SELECT gen_random_uuid(), now(), now(), s.id,
            COALESCE((SELECT MAX(v.number) FROM skill_versions v WHERE v.skill_id = s.id), 0) + 1,
            s.bundle || jsonb_build_object('title', s.bundle->>'name')
        FROM skills s
    """)
    op.execute("""
        UPDATE agent_skills a SET version_id = (
            SELECT v.id FROM skill_versions v WHERE v.skill_id = a.skill_id
            ORDER BY v.number DESC LIMIT 1
        )
    """)
    op.create_foreign_key(
        "agent_skills_version_id_fkey",
        "agent_skills",
        "skill_versions",
        ["version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column("agent_skills", "version_id", nullable=False)
    op.execute(
        "UPDATE skills SET bundle = bundle || jsonb_build_object('title', bundle->>'name')"
    )
    op.alter_column("skills", "bundle", new_column_name="draft")
