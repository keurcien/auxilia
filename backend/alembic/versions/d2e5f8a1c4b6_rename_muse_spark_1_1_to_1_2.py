"""rename muse-spark-1.1 to muse-spark-1.2

Meta's whitelist entry was bumped in place (muse-spark-1.1 -> muse-spark-1.2).
Editing the seed migration only affects fresh databases, so this data migration
repoints existing rows — same approach as f1a2b3c4d5e6.

Renaming rather than delete-and-insert preserves is_enabled and is_default, so
workspaces already on Meta keep working without an admin re-opting in. threads
and triggers pin the raw model_id string and would otherwise raise
ModelUnavailableError (409) on every run.

Revision ID: d2e5f8a1c4b6
Revises: c8f4e2a91d05
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e5f8a1c4b6'
down_revision: Union[str, Sequence[str], None] = 'c8f4e2a91d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD = "muse-spark-1.1"
NEW = "muse-spark-1.2"

# models has UNIQUE(provider, model_id). The whitelist ships from a CDN ahead of
# this deploy, so an admin may already have enabled the new id by hand — drop the
# stale row instead of colliding on the rename.
# ponytail: if that stale row held is_default, the workspace falls back to the
# first available model (ModelService.get_default_model_id). Re-flagging is one
# admin click; carrying the flag over isn't worth the extra statement.
_DEDUPE = (
    "DELETE FROM models WHERE provider = 'meta' AND model_id = :old AND EXISTS "
    "(SELECT 1 FROM models m WHERE m.provider = 'meta' AND m.model_id = :new)"
)

# Static per-table statements (no string interpolation) — the model ids are
# passed as bound parameters, so nothing user-controlled reaches the SQL text.
_STATEMENTS = (
    "UPDATE models SET model_id = :new WHERE provider = 'meta' AND model_id = :old",
    "UPDATE triggers SET model_id = :new WHERE model_id = :old",
    "UPDATE threads SET model_id = :new WHERE model_id = :old",
)


def _rename(old: str, new: str) -> None:
    for sql in (_DEDUPE, *_STATEMENTS):
        op.execute(sa.text(sql).bindparams(old=old, new=new))


def upgrade() -> None:
    _rename(OLD, NEW)


def downgrade() -> None:
    _rename(NEW, OLD)
