"""add reasoning effort to threads and triggers, collapse GLM pseudo-models

Revision ID: a1d4c9e72b58
Revises: 7c5a92e14b03
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1d4c9e72b58"
down_revision: Union[str, Sequence[str], None] = "7c5a92e14b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Lightweight Core table handles for the data migration — everything below is
# built from these constructs (no raw SQL strings anywhere).
def _model_tables() -> tuple[sa.TableClause, sa.TableClause]:
    threads = sa.table(
        "threads", sa.column("model_id"), sa.column("reasoning_effort")
    )
    triggers = sa.table(
        "triggers", sa.column("model_id"), sa.column("reasoning_effort")
    )
    return threads, triggers


_models = sa.table(
    "models",
    sa.column("id"),
    sa.column("provider"),
    sa.column("model_id"),
    sa.column("is_enabled"),
    sa.column("is_default"),
    sa.column("created_at"),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "threads",
        sa.Column("reasoning_effort", sa.String(), nullable=True),
    )
    op.add_column(
        "triggers",
        sa.Column("reasoning_effort", sa.String(length=32), nullable=True),
    )

    # The former glm-5.2-max / glm-5.2-high pseudo-models encoded the GLM
    # thinking level in the model id. The level is now a per-thread
    # reasoning_effort and the id is the OpenRouter slug, so rewrite every
    # stored reference.
    for tbl in _model_tables():
        for old_id, effort in (("glm-5.2-max", "max"), ("glm-5.2-high", "high")):
            op.execute(
                sa.update(tbl)
                .where(tbl.c.model_id == old_id)
                .values(model_id="z-ai/glm-5.2", reasoning_effort=effort)
            )

    # Merge the two enablement rows (admin decisions) into one: enabled /
    # default if either pseudo-model was. Keep one row (rewrite its id),
    # delete the other — the single-default partial unique index stays
    # satisfied because at most one of the two could have been the default.
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_models.c.id, _models.c.is_enabled, _models.c.is_default)
        .where(
            _models.c.provider == "openrouter",
            _models.c.model_id.in_(["glm-5.2-max", "glm-5.2-high"]),
        )
        .order_by(_models.c.created_at)
    ).fetchall()
    if rows:
        keep = rows[0]
        merged_enabled = any(r.is_enabled for r in rows)
        merged_default = any(r.is_default for r in rows)
        for r in rows[1:]:
            bind.execute(sa.delete(_models).where(_models.c.id == r.id))
        bind.execute(
            sa.update(_models)
            .where(_models.c.id == keep.id)
            .values(
                model_id="z-ai/glm-5.2",
                is_enabled=merged_enabled,
                is_default=merged_default,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Re-split by the stored effort level (max was the old default id).
    for tbl in _model_tables():
        op.execute(
            sa.update(tbl)
            .where(tbl.c.model_id == "z-ai/glm-5.2")
            .values(
                model_id=sa.case(
                    (tbl.c.reasoning_effort == "high", "glm-5.2-high"),
                    else_="glm-5.2-max",
                )
            )
        )
    op.execute(
        sa.update(_models)
        .where(
            _models.c.provider == "openrouter",
            _models.c.model_id == "z-ai/glm-5.2",
        )
        .values(model_id="glm-5.2-max")
    )
    op.drop_column("triggers", "reasoning_effort")
    op.drop_column("threads", "reasoning_effort")
