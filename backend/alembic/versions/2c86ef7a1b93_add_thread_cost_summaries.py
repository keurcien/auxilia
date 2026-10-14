"""Compact thread cost summaries and a singleton backfill job.

Revision ID: 2c86ef7a1b93
Revises: 8a40e1b2c3d4
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "2c86ef7a1b93"
down_revision = "8a40e1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "thread_costs",
        sa.Column("thread_id", sa.String(), sa.ForeignKey("threads.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("total_cost", sa.Numeric(38, 18), nullable=True),
        sa.Column("known_cost", sa.Numeric(38, 18), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("pricing_hash", sa.String(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "cost_backfill",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True)),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("cursor", sa.String()),
        sa.Column("cursor_created_at", sa.DateTime(timezone=True)),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("incomplete", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String()),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previous_cost", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column("new_cost", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column("unpriced_models", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default="[]"),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("catalog", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_cost_backfill_singleton"),
    )
    op.execute(
        "INSERT INTO cost_backfill (id, job_id, status, processed, skipped, failed, incomplete, catalog) "
        "VALUES (1, '00000000-0000-0000-0000-000000000000', 'idle', 0, 0, 0, 0, '[]')"
    )
    op.create_index("ix_threads_created_at_id", "threads", ["created_at", "id"])


def downgrade():
    op.drop_index("ix_threads_created_at_id", table_name="threads")
    op.drop_table("cost_backfill")
    op.drop_table("thread_costs")
