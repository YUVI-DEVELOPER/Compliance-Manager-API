from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.schemas.audit_review_schema import AuditReviewSchedulePatchRequest, AuditReviewScheduleUpsertRequest
from app.services.audit_review_metadata import FULL_GXP_AUDIT_TRAIL_TYPES, get_selected_audit_trail_types
from app.services.audit_review_scheduler_service import (
    AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED,
    AUDIT_RETRIEVAL_MODE_CUSTOM,
    ScheduleExecution,
    _add_frequency,
    _audit_retrieval_range,
    _finish_schedule_run,
    _next_custom_audit_range_after_run,
    _payload_end_condition,
    _review_window_days,
    _run_summary_matches_schedule,
    _schedule_audit_retrieval_mode,
    _validate_final_schedule_config,
    calculate_next_run_dt,
)
from app.services.audit_review_service import (
    AuditReviewValidationError,
    _audit_lookback_days,
    _oldest_supported_audit_start,
    _review_window_chunks,
)


def test_schedule_schema_accepts_half_yearly_and_annual_frequencies() -> None:
    next_run = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)

    half_yearly = AuditReviewScheduleUpsertRequest(
        frequency="half_yearly",
        review_window_days=182,
        next_run_dt=next_run,
    )
    annual = AuditReviewSchedulePatchRequest(
        frequency="annual",
        review_window_days=365,
        next_run_dt=next_run,
    )

    assert half_yearly.frequency == "HALF_YEARLY"
    assert annual.frequency == "ANNUAL"


def test_schedule_create_defaults_to_full_gxp_audit_scope() -> None:
    payload = AuditReviewScheduleUpsertRequest(
        next_run_dt=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
    )

    assert payload.review_scope == "FULL_GXP"
    selected_types = get_selected_audit_trail_types(
        payload.review_scope,
        payload.selected_audit_trail_types,
        payload.audit_trail_type,
    )
    assert selected_types == FULL_GXP_AUDIT_TRAIL_TYPES


def test_add_frequency_advances_half_yearly_and_annual_from_calendar_anchor() -> None:
    anchor = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)

    assert _add_frequency(anchor, "HALF_YEARLY") == datetime(2026, 7, 31, 9, 0, tzinfo=UTC)
    assert _add_frequency(anchor, "ANNUAL") == datetime(2027, 1, 31, 9, 0, tzinfo=UTC)


def test_schedule_default_review_window_matches_long_period_frequencies() -> None:
    assert _review_window_days(SimpleNamespace(review_window_days=None, frequency="DAILY")) == 1
    assert _review_window_days(SimpleNamespace(review_window_days=None, frequency="WEEKLY")) == 7
    assert _review_window_days(SimpleNamespace(review_window_days=None, frequency="QUARTERLY")) == 90
    assert _review_window_days(SimpleNamespace(review_window_days=None, frequency="HALF_YEARLY")) == 182
    assert _review_window_days(SimpleNamespace(review_window_days=None, frequency="ANNUAL")) == 365
    assert _review_window_days(SimpleNamespace(review_window_days=40, frequency="DAILY")) == 40


def test_half_yearly_custom_cycle_next_run_uses_selected_start_period() -> None:
    schedule = SimpleNamespace(
        frequency="HALF_YEARLY",
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2025, 12, 31, 18, 30, tzinfo=UTC),  # Jan 01, 2026 00:00 Asia/Kolkata
        run_time="22:30",
        cycle_type="CUSTOM_SIX_MONTH_CYCLE",
        run_timing="FIRST_DAY_AFTER_PERIOD_END",
        custom_cycle_start_month=7,
    )

    assert calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC)) == datetime(2026, 7, 1, 17, 0, tzinfo=UTC)


def test_half_yearly_custom_cycle_auto_range_is_full_selected_period() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="HALF_YEARLY",
        review_window_days=182,
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
        cycle_type="CUSTOM_SIX_MONTH_CYCLE",
        custom_cycle_start_month=7,
    )

    review_start, review_end, mode = asyncio.run(
        _audit_retrieval_range(SimpleNamespace(), schedule, datetime(2026, 7, 1, 17, 0, tzinfo=UTC))
    )

    assert mode == "AUTO"
    assert review_start == datetime(2025, 12, 31, 18, 30, tzinfo=UTC)
    assert review_end == datetime(2026, 6, 30, 18, 29, 59, tzinfo=UTC)


def test_half_yearly_ending_period_must_not_precede_start_period() -> None:
    schedule = SimpleNamespace(
        frequency="HALF_YEARLY",
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2026, 6, 30, 18, 30, tzinfo=UTC),  # Jul-Dec 2026 period start
        schedule_end_dt=datetime(2026, 7, 1, 17, 0, tzinfo=UTC),  # Final run for Jan-Jun 2026
        end_condition="END_ON_DATE",
        end_after_runs=None,
        run_time="22:30",
        cycle_type="CUSTOM_SIX_MONTH_CYCLE",
        run_timing="FIRST_DAY_AFTER_PERIOD_END",
        custom_cycle_start_month=7,
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
    )

    with pytest.raises(AuditReviewValidationError, match="same or a later half-year review period"):
        _validate_final_schedule_config(schedule)


def test_annual_calendar_next_run_uses_selected_review_year() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="ANNUAL",
        review_window_days=365,
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2025, 12, 31, 18, 30, tzinfo=UTC),  # Jan 01, 2026 00:00 Asia/Kolkata
        schedule_end_dt=None,
        end_condition="NO_END_DATE",
        end_after_runs=None,
        run_time="01:51",
        cycle_type="CALENDAR_YEAR",
        run_month=None,
        fiscal_year_start_month=None,
    )

    next_run = calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC))

    assert next_run == datetime(2026, 12, 31, 20, 21, tzinfo=UTC)  # Jan 01, 2027 01:51 Asia/Kolkata

    review_start, review_end, mode = asyncio.run(_audit_retrieval_range(SimpleNamespace(), schedule, next_run))

    assert mode == "AUTO"
    assert review_start == datetime(2025, 12, 31, 18, 30, tzinfo=UTC)  # Jan 01, 2026 00:00 Asia/Kolkata
    assert review_end == datetime(2026, 12, 31, 18, 29, 59, tzinfo=UTC)  # Dec 31, 2026 23:59:59 Asia/Kolkata


def test_annual_start_review_year_skips_prior_calendar_year() -> None:
    schedule = SimpleNamespace(
        frequency="ANNUAL",
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2026, 12, 31, 18, 30, tzinfo=UTC),  # Jan 01, 2027 00:00 Asia/Kolkata
        run_time="01:51",
        cycle_type="CALENDAR_YEAR",
        run_month=None,
        fiscal_year_start_month=None,
    )

    next_run = calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC))

    assert next_run == datetime(2027, 12, 31, 20, 21, tzinfo=UTC)  # Jan 01, 2028 01:51 Asia/Kolkata


def test_annual_same_start_and_ending_year_is_valid_until_final_run() -> None:
    schedule = SimpleNamespace(
        frequency="ANNUAL",
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2025, 12, 31, 18, 30, tzinfo=UTC),  # Jan 01, 2026 00:00 Asia/Kolkata
        schedule_end_dt=datetime(2026, 12, 31, 20, 21, tzinfo=UTC),  # Jan 01, 2027 01:51 Asia/Kolkata
        end_condition="END_ON_DATE",
        end_after_runs=None,
        run_time="01:51",
        cycle_type="CALENDAR_YEAR",
        run_month=None,
        fiscal_year_start_month=None,
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
    )

    _validate_final_schedule_config(schedule)


def test_annual_ending_year_must_not_precede_start_review_year() -> None:
    schedule = SimpleNamespace(
        frequency="ANNUAL",
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2025, 12, 31, 18, 30, tzinfo=UTC),  # Jan 01, 2026 00:00 Asia/Kolkata
        schedule_end_dt=datetime(2025, 12, 31, 20, 21, tzinfo=UTC),  # Jan 01, 2026 01:51 Asia/Kolkata, final run for 2025
        end_condition="END_ON_DATE",
        end_after_runs=None,
        run_time="01:51",
        cycle_type="CALENDAR_YEAR",
        run_month=None,
        fiscal_year_start_month=None,
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
    )

    with pytest.raises(AuditReviewValidationError, match="Schedule ending year must be the same as or after"):
        _validate_final_schedule_config(schedule)


def test_frequency_change_realigns_next_run_from_last_run() -> None:
    schedule = SimpleNamespace(
        frequency="WEEKLY",
        run_time="11:03",
        day_of_week=3,
        timezone="UTC",
        schedule_start_dt=None,
    )
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)

    assert calculate_next_run_dt(schedule, now) == datetime(2026, 5, 27, 11, 3, tzinfo=UTC)


def test_monthly_schedule_always_uses_first_day_of_next_month() -> None:
    schedule = SimpleNamespace(
        frequency="MONTHLY",
        run_time="09:00",
        timezone="UTC",
        schedule_start_dt=None,
        day_of_month=31,
        use_last_day_of_month=True,
    )

    assert calculate_next_run_dt(schedule, datetime(2026, 1, 31, 10, 0, tzinfo=UTC)) == datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    assert calculate_next_run_dt(schedule, datetime(2026, 2, 28, 10, 0, tzinfo=UTC)) == datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def test_monthly_first_run_clamps_review_period_to_schedule_start_date() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="MONTHLY",
        run_time="01:51",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2026, 5, 29, 18, 30, tzinfo=UTC),  # May 30, 2026 00:00 Asia/Kolkata
        last_run_dt=None,
        day_of_month=1,
        use_last_day_of_month=False,
    )

    next_run = calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC))

    assert next_run == datetime(2026, 5, 31, 20, 21, tzinfo=UTC)  # Jun 01, 2026 01:51 Asia/Kolkata

    review_start, review_end, mode = asyncio.run(_audit_retrieval_range(SimpleNamespace(), schedule, next_run))

    assert mode == "AUTO"
    assert review_start == datetime(2026, 5, 29, 18, 30, tzinfo=UTC)  # May 30, 2026 00:00 Asia/Kolkata
    assert review_end == datetime(2026, 5, 31, 18, 29, 59, tzinfo=UTC)  # May 31, 2026 23:59:59 Asia/Kolkata


def test_monthly_schedule_start_on_month_boundary_skips_prior_month_review() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="MONTHLY",
        run_time="01:51",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2026, 5, 31, 18, 30, tzinfo=UTC),  # Jun 01, 2026 00:00 Asia/Kolkata
        last_run_dt=None,
        day_of_month=1,
        use_last_day_of_month=False,
    )

    next_run = calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC))

    assert next_run == datetime(2026, 6, 30, 20, 21, tzinfo=UTC)  # Jul 01, 2026 01:51 Asia/Kolkata

    review_start, review_end, mode = asyncio.run(_audit_retrieval_range(SimpleNamespace(), schedule, next_run))

    assert mode == "AUTO"
    assert review_start == datetime(2026, 5, 31, 18, 30, tzinfo=UTC)  # Jun 01, 2026 00:00 Asia/Kolkata
    assert review_end == datetime(2026, 6, 30, 18, 29, 59, tzinfo=UTC)  # Jun 30, 2026 23:59:59 Asia/Kolkata


def test_monthly_mid_month_start_uses_next_month_and_clamped_first_period() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="MONTHLY",
        run_time="21:30",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="UTC",
        schedule_start_dt=datetime(2026, 5, 7, 0, 0, tzinfo=UTC),
        last_run_dt=None,
        day_of_month=1,
        use_last_day_of_month=False,
    )

    next_run = calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC))

    assert next_run == datetime(2026, 6, 1, 21, 30, tzinfo=UTC)

    review_start, review_end, mode = asyncio.run(_audit_retrieval_range(SimpleNamespace(), schedule, next_run))

    assert mode == "AUTO"
    assert review_start == datetime(2026, 5, 7, 0, 0, tzinfo=UTC)
    assert review_end == datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)


def test_monthly_auto_range_reference_before_next_run_skips_prior_month() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="MONTHLY",
        run_time="21:30",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="UTC",
        schedule_start_dt=datetime(2026, 5, 7, 0, 0, tzinfo=UTC),
        next_run_dt=datetime(2026, 6, 1, 21, 30, tzinfo=UTC),
        last_run_dt=None,
        day_of_month=1,
        use_last_day_of_month=False,
    )

    review_start, review_end, mode = asyncio.run(
        _audit_retrieval_range(SimpleNamespace(), schedule, datetime(2026, 5, 21, 12, 0, tzinfo=UTC))
    )

    assert mode == "AUTO"
    assert review_start == datetime(2026, 5, 7, 0, 0, tzinfo=UTC)
    assert review_end == datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)


def test_monthly_future_run_reviews_full_calendar_month_after_clamped_first_run() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="MONTHLY",
        run_time="21:30",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="UTC",
        schedule_start_dt=datetime(2026, 5, 7, 0, 0, tzinfo=UTC),
        last_run_dt=datetime(2026, 6, 1, 21, 31, tzinfo=UTC),
        day_of_month=1,
        use_last_day_of_month=False,
    )

    review_start, review_end, mode = asyncio.run(
        _audit_retrieval_range(SimpleNamespace(), schedule, datetime(2026, 7, 1, 21, 30, tzinfo=UTC))
    )

    assert mode == "AUTO"
    assert review_start == datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    assert review_end == datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)


def test_quarterly_start_quarter_reviews_full_calendar_quarter() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="QUARTERLY",
        run_time="01:51",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2026, 3, 31, 18, 30, tzinfo=UTC),  # Apr 01, 2026 00:00 Asia/Kolkata
        last_run_dt=None,
        cycle_type="CALENDAR_QUARTER",
        run_timing="FIRST_DAY_AFTER_PERIOD_END",
    )

    next_run = calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC))

    assert next_run == datetime(2026, 6, 30, 20, 21, tzinfo=UTC)  # Jul 01, 2026 01:51 Asia/Kolkata

    review_start, review_end, mode = asyncio.run(_audit_retrieval_range(SimpleNamespace(), schedule, next_run))

    assert mode == "AUTO"
    assert review_start == datetime(2026, 3, 31, 18, 30, tzinfo=UTC)  # Apr 01, 2026 00:00 Asia/Kolkata
    assert review_end == datetime(2026, 6, 30, 18, 29, 59, tzinfo=UTC)  # Jun 30, 2026 23:59:59 Asia/Kolkata


def test_quarterly_schedule_start_on_quarter_boundary_reviews_that_full_quarter() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="QUARTERLY",
        run_time="01:51",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2026, 6, 30, 18, 30, tzinfo=UTC),  # Jul 01, 2026 00:00 Asia/Kolkata
        last_run_dt=None,
        cycle_type="CALENDAR_QUARTER",
        run_timing="FIRST_DAY_AFTER_PERIOD_END",
    )

    next_run = calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC))

    assert next_run == datetime(2026, 9, 30, 20, 21, tzinfo=UTC)  # Oct 01, 2026 01:51 Asia/Kolkata

    review_start, review_end, mode = asyncio.run(_audit_retrieval_range(SimpleNamespace(), schedule, next_run))

    assert mode == "AUTO"
    assert review_start == datetime(2026, 6, 30, 18, 30, tzinfo=UTC)  # Jul 01, 2026 00:00 Asia/Kolkata
    assert review_end == datetime(2026, 9, 30, 18, 29, 59, tzinfo=UTC)  # Sep 30, 2026 23:59:59 Asia/Kolkata


def test_quarterly_legacy_mid_quarter_anchor_does_not_clamp_review_period() -> None:
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="QUARTERLY",
        run_time="01:51",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
        schedule_start_dt=datetime(2026, 8, 14, 18, 30, tzinfo=UTC),  # Aug 15, 2026 00:00 Asia/Kolkata
        last_run_dt=None,
        cycle_type="CALENDAR_QUARTER",
        run_timing="FIRST_DAY_AFTER_PERIOD_END",
    )

    next_run = calculate_next_run_dt(schedule, datetime(2026, 5, 20, 0, 0, tzinfo=UTC))

    assert next_run == datetime(2026, 9, 30, 20, 21, tzinfo=UTC)  # Oct 01, 2026 01:51 Asia/Kolkata

    review_start, review_end, mode = asyncio.run(_audit_retrieval_range(SimpleNamespace(), schedule, next_run))

    assert mode == "AUTO"
    assert review_start == datetime(2026, 6, 30, 18, 30, tzinfo=UTC)  # Jul 01, 2026 00:00 Asia/Kolkata
    assert review_end == datetime(2026, 9, 30, 18, 29, 59, tzinfo=UTC)  # Sep 30, 2026 23:59:59 Asia/Kolkata


def test_quarterly_schedule_retrieval_mode_is_always_auto() -> None:
    schedule = SimpleNamespace(
        frequency="QUARTERLY",
        audit_retrieval_mode="SINCE_LAST_SUCCESSFUL",
        custom_audit_start_dt=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        custom_audit_end_dt=datetime(2026, 1, 31, 23, 59, tzinfo=UTC),
    )

    assert _schedule_audit_retrieval_mode(schedule) == "AUTO"


def test_quarterly_payload_end_condition_uses_final_run_datetime() -> None:
    final_run = datetime(2027, 1, 1, 16, 0, tzinfo=UTC)

    assert _payload_end_condition("QUARTERLY", final_run, "NO_END_DATE", None) == "END_ON_DATE"


def test_daily_schedule_auto_mode_stays_automatic_completed_period() -> None:
    schedule = SimpleNamespace(frequency="DAILY", audit_retrieval_mode="AUTO")

    assert _schedule_audit_retrieval_mode(schedule) == "AUTO"


def test_daily_schedule_missing_mode_defaults_to_automatic_completed_period() -> None:
    schedule = SimpleNamespace(frequency="DAILY", audit_retrieval_mode=None)

    assert _schedule_audit_retrieval_mode(schedule) == "AUTO"


def test_daily_schedule_auto_reviews_previous_completed_calendar_day() -> None:
    next_run = datetime(2026, 5, 21, 20, 21, tzinfo=UTC)  # May 22, 2026 01:51 Asia/Kolkata.
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="DAILY",
        audit_retrieval_mode="AUTO",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
    )

    review_start, review_end, mode = asyncio.run(
        _audit_retrieval_range(SimpleNamespace(), schedule, next_run)
    )

    assert mode == "AUTO"
    assert review_start == datetime(2026, 5, 20, 18, 30, tzinfo=UTC)
    assert review_end == datetime(2026, 5, 21, 18, 29, 59, tzinfo=UTC)


def test_daily_schedule_custom_dates_are_used_when_saved_mode_is_missing() -> None:
    start = datetime(2026, 4, 1, 17, 33, tzinfo=UTC)
    end = datetime(2026, 5, 20, 17, 34, tzinfo=UTC)
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="DAILY",
        audit_retrieval_mode=None,
        custom_audit_start_dt=start,
        custom_audit_end_dt=end,
        timezone="Asia/Kolkata",
    )

    review_start, review_end, mode = asyncio.run(
        _audit_retrieval_range(SimpleNamespace(), schedule, datetime(2026, 5, 20, 18, 0, tzinfo=UTC))
    )

    assert mode == "CUSTOM"
    assert review_start == start
    assert review_end == end


def test_saved_custom_dates_win_over_stale_rolling_mode() -> None:
    start = datetime(2026, 4, 1, 17, 33, tzinfo=UTC)
    end = datetime(2026, 5, 20, 17, 34, tzinfo=UTC)
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="DAILY",
        audit_retrieval_mode="SINCE_LAST_SUCCESSFUL",
        custom_audit_start_dt=start,
        custom_audit_end_dt=end,
        timezone="Asia/Kolkata",
    )

    review_start, review_end, mode = asyncio.run(
        _audit_retrieval_range(SimpleNamespace(), schedule, datetime(2026, 5, 20, 18, 0, tzinfo=UTC))
    )

    assert mode == "CUSTOM"
    assert review_start == start
    assert review_end == end


def test_custom_schedule_period_rolls_forward_to_next_scheduled_run() -> None:
    schedule = SimpleNamespace(
        frequency="DAILY",
        next_run_dt=datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
    )
    review_start = datetime(2026, 4, 1, 18, 0, tzinfo=UTC)
    review_end = datetime(2026, 5, 20, 18, 0, tzinfo=UTC)

    next_start, next_end = _next_custom_audit_range_after_run(schedule, review_start, review_end)

    assert next_start == review_end
    assert next_end == datetime(2026, 6, 1, 15, 0, tzinfo=UTC)


class _FakeAsyncDb:
    def __init__(self, run: SimpleNamespace, schedule: SimpleNamespace) -> None:
        self.run = run
        self.schedule = schedule

    async def execute(self, statement):  # noqa: ANN001 - minimal test double for SQLAlchemy result use.
        text = str(statement)
        if "audit_review_schedule_run" in text:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: self.run))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: self.schedule))

    async def commit(self) -> None:
        return None


def test_daily_manual_custom_range_is_cleared_after_successful_run() -> None:
    run = SimpleNamespace(
        run_id="run-1",
        status="STARTED",
        completed_at=None,
        message=None,
        error_message=None,
        job_id=None,
        run_summary_json={},
    )
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        last_run_dt=None,
        last_job_id=None,
        next_run_dt=datetime(2026, 5, 30, 11, 23, tzinfo=UTC),
        frequency="DAILY",
        timezone="Asia/Kolkata",
        audit_retrieval_mode=AUDIT_RETRIEVAL_MODE_CUSTOM,
        custom_audit_start_dt=datetime(2026, 4, 1, 0, 31, tzinfo=UTC),
        custom_audit_end_dt=datetime(2026, 5, 1, 11, 23, tzinfo=UTC),
        modified_dt=None,
    )
    execution = ScheduleExecution(
        run_id="run-1",
        schedule_id="schedule-1",
        asset_id="asset-1",
        audit_trail_type="login_audit_trail",
        review_scope="LOGIN_ONLY",
        selected_audit_trail_types=["login_audit_trail"],
        vault_dns=None,
        veeva_instance_name=None,
        veeva_app_name=None,
        frequency="DAILY",
        audit_retrieval_mode=AUDIT_RETRIEVAL_MODE_CUSTOM,
        timezone_name="Asia/Kolkata",
        business_start_hour=8,
        business_end_hour=18,
        review_start_dt=datetime(2026, 4, 1, 0, 31, tzinfo=UTC),
        review_end_dt=datetime(2026, 5, 1, 11, 23, tzinfo=UTC),
        started_at=datetime(2026, 5, 21, 0, 31, tzinfo=UTC),
        requested_by="audit-review-scheduler",
        trigger_mode="SCHEDULED_MANUAL",
    )

    asyncio.run(
        _finish_schedule_run(
            _FakeAsyncDb(run, schedule),
            execution,
            status_value=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED,
            message="completed",
        )
    )

    assert schedule.audit_retrieval_mode == "AUTO"
    assert schedule.custom_audit_start_dt is None
    assert schedule.custom_audit_end_dt is None


def test_daily_since_last_successful_is_treated_as_automatic_completed_period() -> None:
    reference = datetime(2026, 5, 21, 20, 21, tzinfo=UTC)
    schedule = SimpleNamespace(
        schedule_id="schedule-1",
        frequency="DAILY",
        review_window_days=30,
        audit_retrieval_mode="SINCE_LAST_SUCCESSFUL",
        custom_audit_start_dt=None,
        custom_audit_end_dt=None,
        timezone="Asia/Kolkata",
    )

    review_start, review_end, mode = asyncio.run(
        _audit_retrieval_range(
            SimpleNamespace(),
            schedule,
            reference,
            use_last_successful_anchor=False,
        )
    )

    assert mode == "AUTO"
    assert review_start == datetime(2026, 5, 20, 18, 30, tzinfo=UTC)
    assert review_end == datetime(2026, 5, 21, 18, 29, 59, tzinfo=UTC)


def test_extraction_review_window_is_chunked_for_veeva_range_limit() -> None:
    start = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    end = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)

    chunks = _review_window_chunks(start, end, 14)

    assert chunks == [
        (datetime(2026, 4, 20, 10, 0, tzinfo=UTC), datetime(2026, 5, 4, 10, 0, tzinfo=UTC)),
        (datetime(2026, 5, 4, 10, 0, tzinfo=UTC), datetime(2026, 5, 18, 10, 0, tzinfo=UTC)),
        (datetime(2026, 5, 18, 10, 0, tzinfo=UTC), datetime(2026, 5, 20, 10, 0, tzinfo=UTC)),
    ]


def test_veeva_audit_lookback_is_capped_to_endpoint_limit() -> None:
    client = SimpleNamespace(settings=SimpleNamespace(VEEVA_AUDIT_LOOKBACK_DAYS=90))

    assert _audit_lookback_days(client) == 30


def test_veeva_audit_lookback_allows_calendar_boundary_for_local_review_start() -> None:
    reference = datetime(2026, 5, 21, 13, 44, 41, tzinfo=UTC)

    oldest_supported_start = _oldest_supported_audit_start(reference, 20)

    assert oldest_supported_start == datetime(2026, 4, 30, 13, 44, 41, tzinfo=UTC)
    assert datetime(2026, 4, 30, 18, 30, tzinfo=UTC) >= oldest_supported_start


def test_veeva_audit_lookback_does_not_extend_endpoint_cap() -> None:
    reference = datetime(2026, 5, 21, 13, 44, 41, tzinfo=UTC)

    assert _oldest_supported_audit_start(reference, 30) == datetime(2026, 4, 21, 13, 44, 41, tzinfo=UTC)


def test_scheduler_incremental_anchor_requires_same_scope_and_selected_types() -> None:
    schedule = SimpleNamespace(
        review_scope="FULL_GXP",
        selected_audit_trail_types_json=FULL_GXP_AUDIT_TRAIL_TYPES,
        audit_trail_type="login_audit_trail",
    )
    matching_summary = {
        "schedule": {
            "review_scope": "FULL_GXP",
            "selected_audit_trail_types": FULL_GXP_AUDIT_TRAIL_TYPES,
            "audit_trail_type": "login_audit_trail",
        }
    }
    stale_summary = {
        "schedule": {
            "review_scope": "SYSTEM_ONLY",
            "selected_audit_trail_types": ["system_audit_trail"],
            "audit_trail_type": "system_audit_trail",
        }
    }

    assert _run_summary_matches_schedule(schedule, matching_summary) is True
    assert _run_summary_matches_schedule(schedule, stale_summary) is False
