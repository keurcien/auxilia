from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.usage.repository import Granularity, UsageDimension


SUPPORTED_CURRENCIES = ("USD", "EUR", "GBP", "CHF", "CAD")


class UsageScope(StrEnum):
    """What the numbers cover: the caller's own usage, a workspace, or every workspace."""

    personal = "personal"
    workspace = "workspace"
    instance = "instance"


class TokenTotals(BaseModel):
    input: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    output: int = 0
    total: int = 0


class UsageTotals(BaseModel):
    # Display currency. Unpriced calls are counted but contribute no cost.
    cost: float = 0
    calls: int = 0
    unpriced_calls: int = 0
    tokens: TokenTotals = Field(default_factory=TokenTotals)


class UsageCurrency(BaseModel):
    code: str
    usd_rate: float


class UsageSummary(BaseModel):
    month: UsageTotals
    previous_month: UsageTotals
    year: UsageTotals
    all_time: UsageTotals


class UsageSplit(BaseModel):
    # Model id or vendor slug; null for models outside the catalog's vendors.
    key: str | None
    label: str
    # Vendor slug, for its logo.
    vendor: str | None
    summary: UsageSummary


class UsageSummaryResponse(UsageSummary):
    scope: UsageScope
    currency: UsageCurrency
    # Ranked by all-time cost.
    vendors: list[UsageSplit] = Field(default_factory=list)
    models: list[UsageSplit] = Field(default_factory=list)


class UsageSummariesResponse(BaseModel):
    scope: UsageScope
    currency: UsageCurrency
    dimension: UsageDimension
    # Keyed by entity id; entities with no recorded usage are absent.
    items: dict[str, UsageSummary]


class UsageSeriesPoint(BaseModel):
    start: date
    cost: float
    tokens: int
    calls: int
    cost_by_channel: dict[str, float]


class UsageBreakdownRow(BaseModel):
    # Entity id, channel or model id. Null groups deleted entities or, for
    # projects, usage outside any project.
    key: str | None
    label: str
    cost: float
    previous_cost: float
    calls: int
    unpriced_calls: int
    tokens: int
    share: float
    # Vendor slug of model and vendor rows, for their logo.
    vendor: str | None = None


class UsageBudget(BaseModel):
    monthly: float
    month_to_date: float
    projected: float


class UsageReportResponse(BaseModel):
    scope: UsageScope
    currency: UsageCurrency
    start: date
    end: date
    previous_start: date
    previous_end: date
    granularity: Granularity
    totals: UsageTotals
    previous_totals: UsageTotals
    series: list[UsageSeriesPoint]
    breakdowns: dict[UsageDimension, list[UsageBreakdownRow]]
    budget: UsageBudget | None
    tracking_started_at: date | None
    backfill_completed: bool


class UsageSettingsResponse(BaseModel):
    currency: str
    usd_rate: float
    monthly_budget: float | None
    supported_currencies: list[str] = Field(
        default_factory=lambda: list(SUPPORTED_CURRENCIES)
    )


class UsageSettingsUpdate(BaseModel):
    currency: str
    usd_rate: Decimal = Field(gt=0, le=10_000, decimal_places=6)
    monthly_budget: Decimal | None = Field(
        default=None, gt=0, le=1_000_000_000, decimal_places=2
    )

    @field_validator("currency")
    @classmethod
    def _known_currency(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Currency must be one of {', '.join(SUPPORTED_CURRENCIES)}"
            )
        return code
