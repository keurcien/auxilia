"""upgrade langgraph checkpoint schema (checkpoint-postgres 3.1.x)

Revision ID: b7e2f4a9c1d3
Revises: a1d4c9e72b58
Create Date: 2026-09-02 00:00:00.000000

langgraph-checkpoint-postgres 3.0.4 → 3.1.2 ships new internal migrations
(the `checkpoint_writes.task_path` column, delta-based channel-value storage,
segment-scoped namespace matching). The library applies them through its own
`checkpoint_migrations` table via `setup()`, which this project only ever ran
from the base migration (`000000000000`), so an upgraded package would run
against a schema one version behind. `setup()` is idempotent — it applies the
versions the table doesn't have — so this migration simply runs it again.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7e2f4a9c1d3"
down_revision: Union[str, Sequence[str], None] = "a1d4c9e72b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the checkpointer's pending internal migrations."""
    from langgraph.checkpoint.postgres import PostgresSaver

    bind = op.get_bind()
    url = bind.engine.url.set(drivername="postgresql")
    db_url = url.render_as_string(hide_password=False)

    with PostgresSaver.from_conn_string(db_url) as checkpointer:
        checkpointer.setup()


def downgrade() -> None:
    """No-op: the checkpointer's internal migrations are additive (a defaulted
    column), and the previous package version reads the schema unchanged."""
