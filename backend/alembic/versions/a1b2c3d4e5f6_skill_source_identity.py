"""Skill source identity, and the provider a thread's sandbox belongs to.

Two admins connecting the same repository at the same time both passed the
application-level lookup, because nothing in the database said a source *is*
its url, ref and path. An expression index rather than a plain unique
constraint: `subpath` is nullable, and NULLs never collide in a unique index,
so two sources on the same repository root would have been allowed through.

Revision ID: a1b2c3d4e5f6
Revises: 9c1d2e3f4a5b
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "9c1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Collapse any duplicates an existing deployment already holds, keeping
    # the oldest row — its skills are the ones agents are bound to.
    op.execute(
        """
        DELETE FROM skill_sources a
        USING skill_sources b
        WHERE a.url = b.url
          AND a.ref = b.ref
          AND coalesce(a.subpath, '') = coalesce(b.subpath, '')
          AND a.created_at > b.created_at
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_skill_sources_identity "
        "ON skill_sources (url, ref, coalesce(subpath, ''))"
    )
    # Which sandbox row the thread's `sandbox_id` was issued by. Without it a
    # rebinding sent an id from the old provider to the new one, which cannot
    # know it and fails the run instead of starting fresh.
    op.add_column(
        "threads",
        sa.Column("sandbox_source_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_threads_sandbox_source_id",
        "threads",
        "sandboxes",
        ["sandbox_source_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_threads_sandbox_source_id", "threads", type_="foreignkey")
    op.drop_column("threads", "sandbox_source_id")
    op.execute("DROP INDEX IF EXISTS uq_skill_sources_identity")
