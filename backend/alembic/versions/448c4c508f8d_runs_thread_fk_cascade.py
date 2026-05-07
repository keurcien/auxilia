"""runs.thread_id: ON DELETE CASCADE

Revision ID: 448c4c508f8d
Revises: 595341e814b4
Create Date: 2026-05-07

The original migration created the FK without a delete rule, so dropping a
thread that still has runs (e.g. archiving an old conversation) raises
ForeignKeyViolation. Runs are an append-only audit of activity on a thread —
when the thread goes, the runs go.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "448c4c508f8d"
down_revision: Union[str, Sequence[str], None] = "595341e814b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_NAME = "runs_thread_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK_NAME, "runs", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        source_table="runs",
        referent_table="threads",
        local_cols=["thread_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "runs", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        source_table="runs",
        referent_table="threads",
        local_cols=["thread_id"],
        remote_cols=["id"],
    )
