"""Pure schedule math for triggers — no DB, no service state.

A schedule is stored as ``(cron_expression, timezone)`` and materialized into a
single ``next_run_at`` (UTC). All occurrence computation lives here so the
service and the schedule-preview endpoint share one implementation.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from app.exceptions import DomainValidationError


def ensure_valid_schedule(cron_expression: str, timezone: str) -> None:
    """Raise ``DomainValidationError`` unless the cron + IANA timezone parse."""
    if not croniter.is_valid(cron_expression):
        raise DomainValidationError(f"Invalid cron expression: {cron_expression!r}")
    try:
        ZoneInfo(timezone)
    except Exception as exc:
        raise DomainValidationError(f"Unknown timezone: {timezone!r}") from exc


def compute_next_run_at(
    cron_expression: str, timezone: str, after: datetime
) -> datetime:
    """Next occurrence strictly after ``after``, returned in UTC.

    The cron is evaluated in the schedule's timezone ("8am" means 8am *there*,
    DST included), then normalized to UTC for storage and comparison.
    """
    local_after = after.astimezone(ZoneInfo(timezone))
    next_local: datetime = croniter(cron_expression, local_after).get_next(datetime)
    return next_local.astimezone(UTC)


def compute_next_run_ats(
    cron_expression: str, timezone: str, after: datetime, count: int
) -> list[datetime]:
    """The next ``count`` occurrences after ``after``, in UTC (for previews)."""
    local_after = after.astimezone(ZoneInfo(timezone))
    it = croniter(cron_expression, local_after)
    return [it.get_next(datetime).astimezone(UTC) for _ in range(count)]
