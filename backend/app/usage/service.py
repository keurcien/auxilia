import re
from calendar import monthrange
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DomainValidationError, PermissionDeniedError
from app.model_providers.whitelist import SupportedModel, get_whitelist
from app.usage.models import UsageChannel
from app.usage.repository import (
    Granularity,
    UsageDimension,
    UsageFilter,
    UsageLedgerStateRepository,
    UsageRepository,
    UsageSettingsRepository,
)
from app.usage.schemas import (
    TokenTotals,
    UsageBreakdownRow,
    UsageBudget,
    UsageCurrency,
    UsageReportResponse,
    UsageScope,
    UsageSeriesPoint,
    UsageSettingsResponse,
    UsageSettingsUpdate,
    UsageSplit,
    UsageSummariesResponse,
    UsageSummary,
    UsageSummaryResponse,
    UsageTotals,
)
from app.users.models import UserDB
from app.workspaces.models import WorkspaceRole


DEFAULT_CURRENCY = "EUR"
DEFAULT_USD_RATE = Decimal("0.86")

MAX_SERIES_POINTS = 800
BREAKDOWN_LIMIT = 50

CHANNEL_LABELS = {
    UsageChannel.web: "Web chat",
    UsageChannel.api: "API",
    UsageChannel.slack: "Slack",
    UsageChannel.telegram: "Telegram",
    UsageChannel.whatsapp: "WhatsApp",
    UsageChannel.schedule: "Scheduled triggers",
    UsageChannel.webhook: "Webhook triggers",
    UsageChannel.trigger: "Deleted triggers",
}

MISSING_LABELS = {
    UsageDimension.agent: "Deleted agent",
    UsageDimension.project: "No project",
    UsageDimension.trigger: "Deleted trigger",
    UsageDimension.user: "Deleted user",
    UsageDimension.model: "Unknown model",
    UsageDimension.workspace: "Deleted workspace",
}

OTHER_VENDOR_LABEL = "Other"
# Vendors are grouped from every model, not the top of a ranking.
ALL_MODELS = 1000

SUMMARY_DIMENSIONS = (
    UsageDimension.agent,
    UsageDimension.project,
    UsageDimension.trigger,
    UsageDimension.user,
)

_TIMEZONE_NAME = re.compile(r"^[A-Za-z0-9_+\-/]{1,64}$")


def parse_timezone(name: str) -> ZoneInfo:
    # The name is inlined into SQL (see UsageRepository.series), so the
    # character check comes first and is not just a nicety.
    if not _TIMEZONE_NAME.match(name):
        raise DomainValidationError("Invalid timezone")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DomainValidationError("Invalid timezone") from exc


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def _bucket_start(day: date, granularity: Granularity) -> date:
    if granularity is Granularity.week:
        return day - timedelta(days=day.weekday())
    if granularity is Granularity.month:
        return day.replace(day=1)
    return day


def _next_bucket(day: date, granularity: Granularity) -> date:
    if granularity is Granularity.day:
        return day + timedelta(days=1)
    if granularity is Granularity.week:
        return day + timedelta(days=7)
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def _previous_month_start(month_start: date) -> date:
    return (month_start - timedelta(days=1)).replace(day=1)


class _Converter:
    def __init__(self, usd_rate: Decimal):
        self.usd_rate = usd_rate

    def money(self, usd: Any) -> float:
        return float(Decimal(usd or 0) * self.usd_rate)

    def totals(self, row: Row, prefix: str = "") -> UsageTotals:
        def value(name: str) -> int:
            return int(getattr(row, f"{prefix}{name}") or 0)

        return UsageTotals(
            cost=self.money(getattr(row, f"{prefix}cost_usd")),
            calls=value("calls"),
            unpriced_calls=value("unpriced_calls"),
            tokens=TokenTotals(
                input=value("input_tokens"),
                cache_read=value("cache_read_tokens"),
                cache_creation=value("cache_creation_tokens"),
                output=value("output_tokens"),
                total=value("total_tokens"),
            ),
        )


def _minus(left: UsageTotals, right: UsageTotals) -> UsageTotals:
    return UsageTotals(
        cost=max(left.cost - right.cost, 0),
        calls=left.calls - right.calls,
        unpriced_calls=left.unpriced_calls - right.unpriced_calls,
        tokens=TokenTotals(
            **{
                name: getattr(left.tokens, name) - getattr(right.tokens, name)
                for name in TokenTotals.model_fields
            }
        ),
    )


def _add(left: UsageTotals, right: UsageTotals) -> UsageTotals:
    return UsageTotals(
        cost=left.cost + right.cost,
        calls=left.calls + right.calls,
        unpriced_calls=left.unpriced_calls + right.unpriced_calls,
        tokens=TokenTotals(
            **{
                name: getattr(left.tokens, name) + getattr(right.tokens, name)
                for name in TokenTotals.model_fields
            }
        ),
    )


def _add_summaries(left: UsageSummary, right: UsageSummary) -> UsageSummary:
    return UsageSummary(
        **{
            name: _add(getattr(left, name), getattr(right, name))
            for name in UsageSummary.model_fields
        }
    )


def _ranked(splits: Iterable[UsageSplit]) -> list[UsageSplit]:
    return sorted(
        splits,
        key=lambda split: (
            split.summary.all_time.cost,
            split.summary.all_time.tokens.total,
        ),
        reverse=True,
    )


async def _catalog() -> dict[str, SupportedModel]:
    return {model.model_id: model for model in await get_whitelist()}


def _vendor(
    model_id: str | None, catalog: dict[str, SupportedModel]
) -> tuple[str | None, str]:
    """Slug and name of the model's creator; models outside the catalog are "Other"."""
    model = catalog.get(model_id) if model_id else None
    if model is None:
        return None, OTHER_VENDOR_LABEL
    return model.chef_slug, model.chef or model.provider


def _share(cost: float, tokens: int, totals: UsageTotals) -> float:
    if totals.cost > 0:
        return cost / totals.cost
    return tokens / totals.tokens.total if totals.tokens.total else 0


class UsageService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = UsageRepository(db)
        self.settings = UsageSettingsRepository(db)
        self.state = UsageLedgerStateRepository(db)

    # Scope ----------------------------------------------------------------

    def resolve_scope(
        self,
        user: UserDB,
        workspace_id: UUID,
        requested: UsageScope | None,
        **filters: UUID | str | None,
    ) -> tuple[UsageScope, UsageFilter]:
        """Members see their own usage; admins their workspace; the instance
        owner may ask for every workspace."""
        is_admin = user.role == WorkspaceRole.admin
        if requested is UsageScope.instance:
            if not user.is_instance_owner:
                raise PermissionDeniedError(
                    "Only the instance owner can view every workspace"
                )
            return UsageScope.instance, UsageFilter(workspace_id=None, **filters)
        if requested is UsageScope.workspace and not is_admin:
            raise PermissionDeniedError("Workspace usage requires the admin role")
        if is_admin and requested is not UsageScope.personal:
            return UsageScope.workspace, UsageFilter(
                workspace_id=workspace_id, **filters
            )
        filters["user_id"] = user.id
        return UsageScope.personal, UsageFilter(workspace_id=workspace_id, **filters)

    # Settings -------------------------------------------------------------

    async def get_settings(self, workspace_id: UUID) -> UsageSettingsResponse:
        row = await self.settings.get_for_workspace(workspace_id)
        if row is None:
            return UsageSettingsResponse(
                currency=DEFAULT_CURRENCY,
                usd_rate=float(DEFAULT_USD_RATE),
                monthly_budget=None,
            )
        return UsageSettingsResponse(
            currency=row.currency,
            usd_rate=float(row.usd_rate),
            monthly_budget=float(row.monthly_budget) if row.monthly_budget else None,
        )

    async def update_settings(
        self, workspace_id: UUID, data: UsageSettingsUpdate
    ) -> UsageSettingsResponse:
        usd_rate = Decimal(1) if data.currency == "USD" else data.usd_rate
        await self.settings.save(
            workspace_id,
            currency=data.currency,
            usd_rate=usd_rate,
            monthly_budget=data.monthly_budget,
        )
        return await self.get_settings(workspace_id)

    async def _currency(self, workspace_id: UUID) -> tuple[UsageCurrency, _Converter]:
        settings = await self.get_settings(workspace_id)
        rate = Decimal(str(settings.usd_rate))
        return (
            UsageCurrency(code=settings.currency, usd_rate=settings.usd_rate),
            _Converter(rate),
        )

    # Summaries ------------------------------------------------------------

    @staticmethod
    def _summary_windows(tz: ZoneInfo) -> dict[str, datetime | None]:
        today = datetime.now(tz).date()
        month_start = today.replace(day=1)
        return {
            "month": _midnight(month_start, tz),
            "since_previous_month": _midnight(_previous_month_start(month_start), tz),
            "year": _midnight(today.replace(month=1, day=1), tz),
            "all_time": None,
        }

    @staticmethod
    def _summary(row: Row, converter: _Converter) -> UsageSummary:
        month = converter.totals(row, "month_")
        return UsageSummary(
            month=month,
            previous_month=_minus(
                converter.totals(row, "since_previous_month_"), month
            ),
            year=converter.totals(row, "year_"),
            all_time=converter.totals(row, "all_time_"),
        )

    async def summary(
        self, scope: UsageScope, usage_filter: UsageFilter, workspace_id: UUID, tz: str
    ) -> UsageSummaryResponse:
        currency, converter = await self._currency(workspace_id)
        windows = self._summary_windows(parse_timezone(tz))
        rows = await self.repository.windowed_totals(usage_filter, windows)
        summary = self._summary(rows[0], converter)
        model_rows = await self.repository.windowed_totals(
            usage_filter, windows, group_by=UsageDimension.model
        )
        catalog = await _catalog()
        models: list[UsageSplit] = []
        vendors: dict[str | None, UsageSplit] = {}
        for row in model_rows:
            model_summary = self._summary(row, converter)
            vendor, vendor_label = _vendor(row.key, catalog)
            model = catalog.get(row.key) if row.key else None
            models.append(
                UsageSplit(
                    key=row.key,
                    label=model.display_name if model else row.key or "Unknown model",
                    vendor=vendor,
                    summary=model_summary,
                )
            )
            group = vendors.get(vendor)
            vendors[vendor] = UsageSplit(
                key=vendor,
                label=vendor_label,
                vendor=vendor,
                summary=_add_summaries(group.summary, model_summary)
                if group
                else model_summary,
            )
        return UsageSummaryResponse(
            scope=scope,
            currency=currency,
            vendors=_ranked(vendors.values()),
            models=_ranked(models),
            **summary.model_dump(),
        )

    async def summaries(
        self,
        scope: UsageScope,
        usage_filter: UsageFilter,
        workspace_id: UUID,
        dimension: UsageDimension,
        tz: str,
        ids: list[UUID] | None = None,
    ) -> UsageSummariesResponse:
        if dimension not in SUMMARY_DIMENSIONS:
            raise DomainValidationError(
                "Summaries are available per agent, project, trigger or user"
            )
        currency, converter = await self._currency(workspace_id)
        rows = await self.repository.windowed_totals(
            usage_filter,
            self._summary_windows(parse_timezone(tz)),
            group_by=dimension,
            keys=ids,
        )
        return UsageSummariesResponse(
            scope=scope,
            currency=currency,
            dimension=dimension,
            items={
                str(row.key): self._summary(row, converter)
                for row in rows
                if row.key is not None
            },
        )

    # Report ---------------------------------------------------------------

    async def report(
        self,
        scope: UsageScope,
        usage_filter: UsageFilter,
        workspace_id: UUID,
        *,
        start: date | None,
        end: date | None,
        granularity: Granularity,
        tz: str,
    ) -> UsageReportResponse:
        zone = parse_timezone(tz)
        currency, converter = await self._currency(workspace_id)
        today = datetime.now(zone).date()
        end = end or today
        if start is None:
            first = await self.repository.first_occurred_at(usage_filter)
            start = first.astimezone(zone).date() if first else end
        if start > end:
            raise DomainValidationError("The start date must not be after the end date")
        length = (end - start).days + 1
        points = {
            Granularity.day: length,
            Granularity.week: length / 7,
            Granularity.month: length / 30,
        }[granularity]
        if points > MAX_SERIES_POINTS:
            raise DomainValidationError(
                "This range has too many points for its granularity; choose a coarser one"
            )
        previous_end = start - timedelta(days=1)
        previous_start = start - timedelta(days=length)
        range_start, range_end = (
            _midnight(start, zone),
            _midnight(end + timedelta(days=1), zone),
        )
        previous_range = (_midnight(previous_start, zone), range_start)

        totals = converter.totals(
            await self.repository.totals(usage_filter, range_start, range_end)
        )
        previous_totals = converter.totals(
            await self.repository.totals(usage_filter, *previous_range)
        )
        series = await self._series(
            usage_filter, range_start, range_end, start, end, granularity, tz, converter
        )
        dimensions = [
            UsageDimension.channel,
            UsageDimension.agent,
            UsageDimension.project,
            UsageDimension.trigger,
            UsageDimension.model,
            UsageDimension.vendor,
        ]
        if scope is not UsageScope.personal:
            dimensions.append(UsageDimension.user)
        if scope is UsageScope.instance:
            dimensions.append(UsageDimension.workspace)
        breakdowns = {
            dimension: await self._breakdown(
                usage_filter,
                dimension,
                (range_start, range_end),
                previous_range,
                totals,
                converter,
            )
            for dimension in dimensions
        }
        state = await self.state.get()
        return UsageReportResponse(
            scope=scope,
            currency=currency,
            start=start,
            end=end,
            previous_start=previous_start,
            previous_end=previous_end,
            granularity=granularity,
            totals=totals,
            previous_totals=previous_totals,
            series=series,
            breakdowns=breakdowns,
            budget=await self._budget(scope, workspace_id, zone, converter),
            tracking_started_at=(
                state.tracking_started_at.astimezone(zone).date() if state else None
            ),
            backfill_completed=bool(state and state.backfill_completed_at),
        )

    async def _series(
        self,
        usage_filter: UsageFilter,
        range_start: datetime,
        range_end: datetime,
        start: date,
        end: date,
        granularity: Granularity,
        tz: str,
        converter: _Converter,
    ) -> list[UsageSeriesPoint]:
        rows = await self.repository.series(
            usage_filter, range_start, range_end, granularity, tz
        )
        points: dict[date, UsageSeriesPoint] = {}
        cursor = _bucket_start(start, granularity)
        while cursor <= end:
            points[cursor] = UsageSeriesPoint(
                start=cursor, cost=0, tokens=0, calls=0, cost_by_channel={}
            )
            cursor = _next_bucket(cursor, granularity)
        for row in rows:
            point = points.get(row.bucket.date())
            if point is None:
                continue
            cost = converter.money(row.cost_usd)
            point.cost += cost
            point.tokens += int(row.total_tokens)
            point.calls += int(row.calls)
            point.cost_by_channel[row.channel] = (
                point.cost_by_channel.get(row.channel, 0) + cost
            )
        return list(points.values())

    async def _breakdown(
        self,
        usage_filter: UsageFilter,
        dimension: UsageDimension,
        current: tuple[datetime, datetime],
        previous: tuple[datetime, datetime],
        totals: UsageTotals,
        converter: _Converter,
    ) -> list[UsageBreakdownRow]:
        if dimension is UsageDimension.vendor:
            return await self._vendor_breakdown(
                usage_filter, current, previous, totals, converter
            )
        rows = await self.repository.breakdown(
            usage_filter, *current, dimension, BREAKDOWN_LIMIT
        )
        previous_rows = await self.repository.breakdown(
            usage_filter, *previous, dimension, BREAKDOWN_LIMIT * 4
        )
        previous_cost = {
            row.key: converter.money(row.cost_usd) for row in previous_rows
        }
        labels = await self._labels(dimension, [row.key for row in rows])
        catalog = await _catalog() if dimension is UsageDimension.model else {}
        result = []
        for row in rows:
            cost = converter.money(row.cost_usd)
            tokens = int(row.total_tokens)
            result.append(
                UsageBreakdownRow(
                    key=str(row.key) if row.key is not None else None,
                    label=labels.get(row.key)
                    or MISSING_LABELS.get(dimension, "Unknown"),
                    cost=cost,
                    previous_cost=previous_cost.get(row.key, 0),
                    calls=int(row.calls),
                    unpriced_calls=int(row.unpriced_calls),
                    tokens=tokens,
                    share=_share(cost, tokens, totals),
                    vendor=_vendor(row.key, catalog)[0] if catalog else None,
                )
            )
        return result

    async def _vendor_breakdown(
        self,
        usage_filter: UsageFilter,
        current: tuple[datetime, datetime],
        previous: tuple[datetime, datetime],
        totals: UsageTotals,
        converter: _Converter,
    ) -> list[UsageBreakdownRow]:
        catalog = await _catalog()
        rows: dict[str | None, UsageBreakdownRow] = {}
        for row in await self.repository.breakdown(
            usage_filter, *current, UsageDimension.model, ALL_MODELS
        ):
            vendor, label = _vendor(row.key, catalog)
            group = rows.setdefault(
                vendor,
                UsageBreakdownRow(
                    key=vendor,
                    label=label,
                    cost=0,
                    previous_cost=0,
                    calls=0,
                    unpriced_calls=0,
                    tokens=0,
                    share=0,
                    vendor=vendor,
                ),
            )
            group.cost += converter.money(row.cost_usd)
            group.calls += int(row.calls)
            group.unpriced_calls += int(row.unpriced_calls)
            group.tokens += int(row.total_tokens)
        for row in await self.repository.breakdown(
            usage_filter, *previous, UsageDimension.model, ALL_MODELS
        ):
            if (vendor_row := rows.get(_vendor(row.key, catalog)[0])) is not None:
                vendor_row.previous_cost += converter.money(row.cost_usd)
        for group in rows.values():
            group.share = _share(group.cost, group.tokens, totals)
        return sorted(
            rows.values(), key=lambda row: (row.cost, row.tokens), reverse=True
        )

    async def _labels(
        self, dimension: UsageDimension, keys: list[Any]
    ) -> dict[Any, str]:
        present = [key for key in keys if key is not None]
        if dimension is UsageDimension.channel:
            return {key: CHANNEL_LABELS.get(key, key) for key in present}
        if dimension is UsageDimension.model:
            catalog = await _catalog()
            return {
                key: catalog[key].display_name if key in catalog else key
                for key in present
            }
        return await self.repository.labels(dimension, present)

    async def _budget(
        self,
        scope: UsageScope,
        workspace_id: UUID,
        zone: ZoneInfo,
        converter: _Converter,
    ) -> UsageBudget | None:
        if scope is not UsageScope.workspace:
            return None
        settings = await self.get_settings(workspace_id)
        if settings.monthly_budget is None:
            return None
        now = datetime.now(zone)
        month_start = _midnight(now.date().replace(day=1), zone)
        days = monthrange(now.year, now.month)[1]
        month_to_date = converter.totals(
            await self.repository.totals(
                UsageFilter(workspace_id=workspace_id), month_start, None
            )
        ).cost
        # At least a day elapsed: an hour into the month, one run would
        # otherwise project a month of spend from almost nothing.
        elapsed = max((now - month_start).total_seconds(), 86400) / (days * 86400)
        projected = month_to_date / min(elapsed, 1)
        return UsageBudget(
            monthly=settings.monthly_budget,
            month_to_date=month_to_date,
            projected=projected,
        )


def get_usage_service(db: AsyncSession = Depends(get_db)) -> UsageService:
    return UsageService(db)
