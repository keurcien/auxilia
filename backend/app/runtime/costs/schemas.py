from datetime import datetime
from decimal import Decimal
from typing import Literal
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


class StoredThreadCost(BaseModel):
    thread_id: str
    currency: Literal["EUR"] = "EUR"
    summary: dict
    calculated_at: datetime
    stale: bool


class CostAnalytics(BaseModel):
    currency: Literal["EUR"] = "EUR"
    # These are lifetime estimates for a creation-date cohort, not weekly spend.
    threads: int
    calculated_threads: int
    incomplete_threads: int
    stale_threads: int
    total_cost: Decimal | None
    known_cost: Decimal
