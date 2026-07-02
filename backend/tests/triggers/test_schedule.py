from datetime import UTC, datetime

import pytest

from app.exceptions import DomainValidationError
from app.triggers.schedule import (
    compute_next_run_at,
    ensure_valid_schedule,
    list_next_run_ats,
)


class TestEnsureValidSchedule:
    def test_accepts_valid_cron_and_timezone(self):
        ensure_valid_schedule("0 8 * * *", "Europe/Paris")

    def test_rejects_invalid_cron(self):
        with pytest.raises(DomainValidationError, match="cron"):
            ensure_valid_schedule("not a cron", "UTC")

    def test_rejects_unknown_timezone(self):
        with pytest.raises(DomainValidationError, match="timezone"):
            ensure_valid_schedule("0 8 * * *", "Mars/Olympus_Mons")


class TestComputeNextRunAt:
    def test_daily_8am_in_winter_paris(self):
        # 06:00 UTC = 07:00 Paris (CET, UTC+1) → next 08:00 Paris = 07:00 UTC.
        after = datetime(2026, 1, 15, 6, 0, tzinfo=UTC)
        result = compute_next_run_at("0 8 * * *", "Europe/Paris", after)
        assert result == datetime(2026, 1, 15, 7, 0, tzinfo=UTC)

    def test_daily_8am_in_summer_paris(self):
        # 06:30 UTC = 08:30 Paris (CEST, UTC+2): today's 08:00 already passed
        # → next is tomorrow 08:00 Paris = 06:00 UTC.
        after = datetime(2026, 7, 15, 6, 30, tzinfo=UTC)
        result = compute_next_run_at("0 8 * * *", "Europe/Paris", after)
        assert result == datetime(2026, 7, 16, 6, 0, tzinfo=UTC)

    def test_result_is_strictly_after(self):
        # `after` exactly on an occurrence → the *next* one, not the same instant.
        after = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
        result = compute_next_run_at("0 * * * *", "UTC", after)
        assert result == datetime(2026, 7, 15, 9, 0, tzinfo=UTC)


class TestListNextRunAts:
    def test_returns_count_increasing_occurrences(self):
        after = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
        results = list_next_run_ats("*/15 * * * *", "UTC", after, count=4)
        assert len(results) == 4
        assert results == sorted(results)
        assert results[0] == datetime(2026, 7, 15, 0, 15, tzinfo=UTC)
        assert results[-1] == datetime(2026, 7, 15, 1, 0, tzinfo=UTC)
