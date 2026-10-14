from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, model_validator


class BackfillRequest(BaseModel):
    # Thread creation dates, inclusive start / exclusive end; absent = unbounded.
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.start_at and self.end_at and self.start_at >= self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class BackfillResponse(BaseModel):
    job_id: UUID
    status: str
    start_at: datetime | None
    end_at: datetime | None
    processed: int
    skipped: int
    failed: int
    incomplete: int
    last_error: str | None
    total: int
    previous_cost: Decimal
    new_cost: Decimal
    unpriced_models: list[str]
    finished_at: datetime | None


class ThreadCount(BaseModel):
    threads: int
    # Earliest creation date in the range; lets the UI's "All time" show real dates.
    first_created_at: datetime | None = None


class StoredThreadCost(BaseModel):
    thread_id: str
    summary: dict
    calculated_at: datetime
    stale: bool


class CostAnalytics(BaseModel):
    # These are lifetime estimates for a creation-date cohort, not weekly spend.
    threads: int
    calculated_threads: int
    incomplete_threads: int
    stale_threads: int
    total_cost: Decimal | None
    known_cost: Decimal
