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
    for table in ("threads", "triggers"):
        for old_id, effort in (("glm-5.2-max", "max"), ("glm-5.2-high", "high")):
            op.execute(
                sa.text(
                    f"UPDATE {table} "  # noqa: S608 — constant table/id values
                    "SET model_id = 'z-ai/glm-5.2', reasoning_effort = :effort "
                    "WHERE model_id = :old_id"
                ).bindparams(effort=effort, old_id=old_id)
            )

    # Merge the two enablement rows (admin decisions) into one: enabled /
    # default if either pseudo-model was. Keep one row (rewrite its id),
    # delete the other — the single-default partial unique index stays
    # satisfied because at most one of the two could have been the default.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, is_enabled, is_default FROM models "
            "WHERE provider = 'openrouter' "
            "AND model_id IN ('glm-5.2-max', 'glm-5.2-high') "
            "ORDER BY created_at"
        )
    ).fetchall()
    if rows:
        keep = rows[0]
        merged_enabled = any(r.is_enabled for r in rows)
        merged_default = any(r.is_default for r in rows)
        for r in rows[1:]:
            bind.execute(
                sa.text("DELETE FROM models WHERE id = :id").bindparams(id=r.id)
            )
        bind.execute(
            sa.text(
                "UPDATE models SET model_id = 'z-ai/glm-5.2', "
                "is_enabled = :enabled, is_default = :default WHERE id = :id"
            ).bindparams(enabled=merged_enabled, default=merged_default, id=keep.id)
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Re-split by the stored effort level (max was the old default id).
    for table in ("threads", "triggers"):
        op.execute(
            sa.text(
                f"UPDATE {table} "  # noqa: S608 — constant table/id values
                "SET model_id = CASE WHEN reasoning_effort = 'high' "
                "THEN 'glm-5.2-high' ELSE 'glm-5.2-max' END "
                "WHERE model_id = 'z-ai/glm-5.2'"
            )
        )
    op.execute(
        sa.text(
            "UPDATE models SET model_id = 'glm-5.2-max' "
            "WHERE provider = 'openrouter' AND model_id = 'z-ai/glm-5.2'"
        )
    )
    op.drop_column("triggers", "reasoning_effort")
    op.drop_column("threads", "reasoning_effort")
