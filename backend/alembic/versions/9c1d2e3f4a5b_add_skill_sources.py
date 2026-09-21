"""add skill sources

Revision ID: 9c1d2e3f4a5b
Revises: c4d5e6f7a8b9
Create Date: 2026-09-17 00:00:00.000000

Skills from repositories: `skill_sources` (a GitHub/GitLab repository the
workspace syncs, token encrypted), `skill_versions` (the frozen content a
sync found for a sourced skill, by digest), and provenance columns on
`skills` — where a skill came from, the digest it is pinned to, whether the
last sync still found it upstream.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9c1d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "skill_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("github", "gitlab", name="skillsourcekind"),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("ref", sa.String(length=200), nullable=False, server_default="main"),
        sa.Column("subpath", sa.String(length=240), nullable=True),
        sa.Column("encrypted_token", sa.Text(), nullable=True),
        sa.Column("last_revision", sa.String(length=80), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "last_report", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("skill_count", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_skill_sources_owner_id"), "skill_sources", ["owner_id"], unique=False
    )

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(length=80), nullable=False),
        sa.Column("revision", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "digest", name="uq_skill_versions_digest"),
    )
    op.create_index(
        op.f("ix_skill_versions_skill_id"), "skill_versions", ["skill_id"], unique=False
    )
    op.create_index(
        op.f("ix_skill_versions_digest"), "skill_versions", ["digest"], unique=False
    )

    op.add_column("skills", sa.Column("source_id", sa.Uuid(), nullable=True))
    # The repository the content came from, as a URL rather than a foreign key:
    # `source_id` is nulled when the source row goes (ON DELETE SET NULL, which
    # is what makes a disconnect *detach*), and this has to outlive it. It is
    # what a reconnect matches on, so only the repository that left a skill
    # behind can claim it back — matching on the name alone would let any
    # repository that happened to use the name take over another's row, under
    # the id agents are already bound to.
    op.add_column(
        "skills", sa.Column("source_url", sa.String(length=500), nullable=True)
    )
    op.add_column(
        # 500, not 240: `source_path` is repo-root-relative, so a source's
        # `subpath` (itself up to 240) is part of it.
        "skills", sa.Column("source_path", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "skills", sa.Column("source_revision", sa.String(length=80), nullable=True)
    )
    op.add_column("skills", sa.Column("digest", sa.String(length=80), nullable=True))
    op.add_column(
        "skills",
        sa.Column(
            "missing_upstream",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_foreign_key(
        op.f("fk_skills_source_id_skill_sources"),
        "skills",
        "skill_sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_skills_source_id"), "skills", ["source_id"], unique=False)
    op.create_index(
        op.f("ix_skills_source_url"), "skills", ["source_url"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_skills_source_url"), table_name="skills")
    op.drop_index(op.f("ix_skills_source_id"), table_name="skills")
    op.drop_constraint(op.f("fk_skills_source_id_skill_sources"), "skills", type_="foreignkey")
    op.drop_column("skills", "missing_upstream")
    op.drop_column("skills", "digest")
    op.drop_column("skills", "source_revision")
    op.drop_column("skills", "source_path")
    op.drop_column("skills", "source_url")
    op.drop_column("skills", "source_id")
    op.drop_index(op.f("ix_skill_versions_digest"), table_name="skill_versions")
    op.drop_index(op.f("ix_skill_versions_skill_id"), table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_index(op.f("ix_skill_sources_owner_id"), table_name="skill_sources")
    op.drop_table("skill_sources")
    sa.Enum(name="skillsourcekind").drop(op.get_bind(), checkfirst=True)
