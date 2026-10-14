from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel


class ThreadCostDB(SQLModel, table=True):
    """One replaceable estimate per thread. No message IDs or price ledger."""

    __tablename__ = "thread_costs"

    thread_id: str = Field(
        primary_key=True, foreign_key="threads.id", ondelete="CASCADE"
    )
    total_cost: Decimal | None = Field(default=None, sa_column=Column(Numeric(38, 18)))
    known_cost: Decimal = Field(sa_column=Column(Numeric(38, 18), nullable=False))
    complete: bool
    summary: dict = Field(
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    )
    pricing_hash: str
    calculated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class CostBackfillDB(SQLModel, table=True):
    """Singleton job slot: restartable progress without growing a jobs table."""

    __tablename__ = "cost_backfill"
    __table_args__ = (CheckConstraint("id = 1", name="ck_cost_backfill_singleton"),)

    id: int = Field(default=1, primary_key=True)
    job_id: UUID = Field(default_factory=uuid4)
    status: str = "idle"
    start_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    end_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    # Stable membership: exclude threads created after the job was requested.
    requested_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    cursor: str | None = None
    cursor_created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    incomplete: int = 0
    last_error: str | None = None
    # Threads in range when the job was queued: the progress bar's denominator.
    total: int = 0
    # Over updated threads: their saved known_cost before, and after.
    previous_cost: Decimal = Field(
        default=Decimal(0), sa_column=Column(Numeric(38, 18), nullable=False)
    )
    new_cost: Decimal = Field(
        default=Decimal(0), sa_column=Column(Numeric(38, 18), nullable=False)
    )
    # Model ids that had calls without a price, so the UI can name them.
    unpriced_models: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    # Resume using the same rates even if the catalog changes mid-job.
    catalog: list[dict] = Field(
        default_factory=list,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
