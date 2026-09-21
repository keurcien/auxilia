"""Skill source identity, and the provider a thread's sandbox belongs to.

Two admins connecting the same repository at the same time both passed the
application-level lookup, because nothing in the database said a source *is*
its url, ref and path. An expression index rather than a plain unique
constraint: `subpath` is nullable, and NULLs never collide in a unique index,
so two sources on the same repository root would have been allowed through.

Revision ID: 2376289a83e0
Revises: 9c1d2e3f4a5b
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "2376289a83e0"
down_revision: str | Sequence[str] | None = "9c1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Collapse any duplicates an existing deployment already holds, keeping
    # the oldest row — its skills are the ones agents are bound to.
    #
    # `(created_at, id)` orders them, not `created_at` alone: rows inserted in
    # the same transaction share a timestamp, and `>` then deletes neither, so
    # the index below would fail and block the upgrade.
    #
    # The skills of a losing row are repointed first. `skills.source_id` is
    # ON DELETE SET NULL, so deleting it would quietly turn a sourced skill
    # into an in-app one — editable, unpinned, no longer tracking anything.
    op.execute(
        """
        UPDATE skills s
        SET source_id = keep.id
        FROM skill_sources a
        JOIN LATERAL (
            SELECT b.id FROM skill_sources b
            WHERE b.url = a.url
              AND b.ref = a.ref
              AND coalesce(b.subpath, '') = coalesce(a.subpath, '')
            ORDER BY b.created_at, b.id
            LIMIT 1
        ) keep ON TRUE
        WHERE s.source_id = a.id AND keep.id <> a.id
        """
    )
    op.execute(
        """
        DELETE FROM skill_sources a
        USING skill_sources b
        WHERE a.url = b.url
          AND a.ref = b.ref
          AND coalesce(a.subpath, '') = coalesce(b.subpath, '')
          AND (b.created_at, b.id) < (a.created_at, a.id)
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
