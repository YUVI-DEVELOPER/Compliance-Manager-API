from __future__ import annotations

import asyncio
import calendar
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.asset import Asset
from app.models.audit_review_job import AuditReviewJob
from app.models.audit_review_report import AuditReviewReport
from app.models.audit_review_schedule import AuditReviewSchedule
from app.models.audit_review_schedule_run import AuditReviewScheduleRun
from app.schemas.auth_schema import CurrentUser
from app.schemas.audit_review_schema import (
    AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED,
    AUDIT_REVIEW_SCHEDULE_RUN_STATUS_FAILED,
    AUDIT_REVIEW_SCHEDULE_RUN_STATUS_SKIPPED,
    AUDIT_REVIEW_SCHEDULE_RUN_STATUS_STARTED,
    AUDIT_REVIEW_STATUS_FAILED,
    AuditReviewAnalyzeRequest,
    AuditReviewJobCreateRequest,
    AuditReviewJobDetailResponse,
    AuditReviewReportGenerateResponse,
    AuditReviewSchedulePatchRequest,
    AuditReviewSchedulerRunDueResponse,
    AuditReviewScheduleResponse,
    AuditReviewScheduleRunNowResponse,
    AuditReviewScheduleRunResponse,
    AuditReviewScheduleUpsertRequest,
    DEFAULT_AUDIT_TRAIL_TYPE,
    PrepareNotificationsRequest,
)
from app.services.audit_review_report_service import generate_audit_review_report
from app.services.audit_review_metadata import (
    AuditReviewMetadataError,
    get_selected_audit_trail_types,
    resolve_review_scope,
)
from app.services.audit_review_notification_service import prepare_audit_review_notifications
from app.services.audit_review_workflow_metadata import build_report_workflow_metadata
from app.services.audit_review_service import (
    AuditReviewNotFoundError,
    AuditReviewServiceError,
    AuditReviewValidationError,
    analyze_audit_review_job,
    build_audit_review_candidate_key,
    create_audit_review_job,
    extract_audit_review_job,
    get_audit_review_job,
)


DEFAULT_SCHEDULE_TIMEZONE = "Asia/Kolkata"
DEFAULT_BUSINESS_START_HOUR = 9
DEFAULT_BUSINESS_END_HOUR = 18
DEFAULT_REVIEW_WINDOW_DAYS = 30
DEFAULT_DAILY_REVIEW_WINDOW_DAYS = 1
MAX_REVIEW_WINDOW_DAYS = 366
END_CONDITION_NO_END_DATE = "NO_END_DATE"
END_CONDITION_END_ON_DATE = "END_ON_DATE"
END_CONDITION_END_AFTER_RUNS = "END_AFTER_RUNS"
AUDIT_RETRIEVAL_MODE_AUTO = "AUTO"
AUDIT_RETRIEVAL_MODE_SINCE_LAST_SUCCESSFUL = "SINCE_LAST_SUCCESSFUL"
AUDIT_RETRIEVAL_MODE_CUSTOM = "CUSTOM"
RUN_TIMING_FIRST_DAY_AFTER_PERIOD_END = "FIRST_DAY_AFTER_PERIOD_END"
RUN_TIMING_CUSTOM_RUN_DAY = "CUSTOM_RUN_DAY"
CYCLE_TYPE_CALENDAR_QUARTER = "CALENDAR_QUARTER"
CYCLE_TYPE_CUSTOM_QUARTER = "CUSTOM_QUARTER_CYCLE"
CYCLE_TYPE_CALENDAR_HALF_YEAR = "CALENDAR_HALF_YEAR"
CYCLE_TYPE_CUSTOM_SIX_MONTH = "CUSTOM_SIX_MONTH_CYCLE"
CYCLE_TYPE_CALENDAR_YEAR = "CALENDAR_YEAR"
CYCLE_TYPE_FISCAL_YEAR = "FISCAL_YEAR"
DEFAULT_VEEVA_AUDIT_LOOKBACK_DAYS = 20
VEEVA_AUDIT_LOOKBACK_SAFETY_MARGIN = timedelta(minutes=5)
DEFAULT_SCHEDULER_ACTOR = "audit-review-scheduler"
SCHEDULED_DRAFT_READY_MESSAGE = "Draft report generated and pending QA review."
STARTED_RUN_STALE_AFTER = timedelta(hours=6)
FIXED_TIMEZONE_FALLBACKS: dict[str, tzinfo] = {
    "UTC": UTC,
    "Asia/Kolkata": timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata"),
    "Asia/Calcutta": timezone(timedelta(hours=5, minutes=30), "Asia/Calcutta"),
}
SECRET_PATTERN = re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|session_id)=([^&\s]+)")
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduleExecution:
    run_id: uuid.UUID
    schedule_id: uuid.UUID
    asset_id: uuid.UUID
    audit_trail_type: str
    review_scope: str
    selected_audit_trail_types: list[str]
    vault_dns: str | None
    veeva_instance_name: str | None
    veeva_app_name: str | None
    frequency: str
    audit_retrieval_mode: str
    timezone_name: str
    business_start_hour: int
    business_end_hour: int
    review_start_dt: datetime
    review_end_dt: datetime
    started_at: datetime
    requested_by: str | None
    trigger_mode: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _to_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _safe_error_message(value: Any) -> str:
    text = str(value or "Audit review scheduler failed.").strip()
    text = SECRET_PATTERN.sub(r"\1=***", text)
    text = BEARER_PATTERN.sub("Bearer ***", text)
    return text[:1000]


def _resolve_schedule_selection(
    review_scope: str | None,
    selected_audit_trail_types: list[str] | None,
    audit_trail_type: str | None,
) -> tuple[str, list[str]]:
    try:
        selected = get_selected_audit_trail_types(review_scope, selected_audit_trail_types, audit_trail_type)
        scope = resolve_review_scope(review_scope, selected, audit_trail_type)
    except AuditReviewMetadataError as exc:
        raise AuditReviewValidationError(exc.message, data=exc.data) from exc
    return scope, selected


def _schedule_selected_types(schedule: AuditReviewSchedule) -> list[str]:
    value = schedule.selected_audit_trail_types_json
    if isinstance(value, list) and value:
        return [str(item) for item in value if str(item).strip()]
    return [schedule.audit_trail_type or DEFAULT_AUDIT_TRAIL_TYPE]


def _zone_info(timezone_name: str | None) -> tzinfo:
    normalized = (timezone_name or DEFAULT_SCHEDULE_TIMEZONE).strip() or DEFAULT_SCHEDULE_TIMEZONE
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        fallback = FIXED_TIMEZONE_FALLBACKS.get(normalized)
        if fallback is not None:
            return fallback
        raise AuditReviewValidationError(
            f"Unsupported timezone: {normalized}",
            data={"timezone": normalized},
        ) from exc


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _add_frequency(value: datetime, frequency: str) -> datetime:
    if frequency == "DAILY":
        return value + timedelta(days=1)
    if frequency == "WEEKLY":
        return value + timedelta(days=7)
    if frequency == "MONTHLY":
        return _add_months(value, 1)
    if frequency == "QUARTERLY":
        return _add_months(value, 3)
    if frequency == "HALF_YEARLY":
        return _add_months(value, 6)
    if frequency == "ANNUAL":
        return _add_months(value, 12)
    raise AuditReviewValidationError("Unsupported audit review schedule frequency.", data={"frequency": frequency})


def _parse_run_time(schedule: AuditReviewSchedule) -> tuple[int, int]:
    value = str(getattr(schedule, "run_time", None) or f"{DEFAULT_BUSINESS_START_HOUR:02d}:00").strip()
    parts = value.split(":")
    if len(parts) != 2:
        raise AuditReviewValidationError("run_time must use HH:mm format")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise AuditReviewValidationError("run_time must use HH:mm format") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise AuditReviewValidationError("run_time must use HH:mm format")
    return hour, minute


def _schedule_base_local(schedule: AuditReviewSchedule, reference_dt: datetime, zone: tzinfo) -> datetime:
    reference_local = _to_utc(reference_dt).astimezone(zone)
    schedule_start_dt = getattr(schedule, "schedule_start_dt", None)
    if schedule_start_dt is None:
        return reference_local
    schedule_start_local = _to_utc(schedule_start_dt).astimezone(zone)
    return max(reference_local, schedule_start_local)


def _date_at_local_time(year: int, month: int, day: int, hour: int, minute: int, zone: tzinfo) -> datetime:
    return datetime(year, month, day, hour, minute, 0, 0, tzinfo=zone)


def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _clamped_day(year: int, month: int, day: int) -> int:
    return min(max(day, 1), _last_day_of_month(year, month))


def _local_weekday_sunday_zero(value: datetime) -> int:
    return (value.weekday() + 1) % 7


def _first_local_candidate_after(candidates: list[datetime], base_local: datetime) -> datetime | None:
    return min((candidate for candidate in candidates if candidate > base_local), default=None)


def _monthly_candidate_day(schedule: AuditReviewSchedule, year: int, month: int) -> int:
    del schedule, year, month
    return 1


def _cycle_start_month(schedule: AuditReviewSchedule, expected_custom_cycle_type: str) -> int:
    cycle_type = str(getattr(schedule, "cycle_type", "") or "").strip().upper()
    if cycle_type == expected_custom_cycle_type:
        start_month = getattr(schedule, "custom_cycle_start_month", None)
        if start_month is None:
            raise AuditReviewValidationError("Custom cycle schedules require custom_cycle_start_month.")
        return max(1, min(int(start_month), 12))
    return 1


def _cycle_run_day(schedule: AuditReviewSchedule, run_anchor: datetime) -> int:
    run_timing = str(getattr(schedule, "run_timing", "") or "").strip().upper()
    if run_timing == RUN_TIMING_FIRST_DAY_AFTER_PERIOD_END:
        return 1
    if run_timing == RUN_TIMING_CUSTOM_RUN_DAY:
        return 1
    raise AuditReviewValidationError("run_timing must be FIRST_DAY_AFTER_PERIOD_END or CUSTOM_RUN_DAY")


def _cycle_run_candidates(
    schedule: AuditReviewSchedule,
    base_local: datetime,
    *,
    span_months: int,
    expected_calendar_cycle_type: str,
    expected_custom_cycle_type: str,
    zone: tzinfo,
) -> list[datetime]:
    cycle_type = str(getattr(schedule, "cycle_type", "") or "").strip().upper()
    if cycle_type not in {expected_calendar_cycle_type, expected_custom_cycle_type}:
        raise AuditReviewValidationError(f"{schedule.frequency} schedules require a valid cycle_type.")
    start_month = _cycle_start_month(schedule, expected_custom_cycle_type)
    hour, minute = _parse_run_time(schedule)
    candidates: list[datetime] = []
    for year in range(base_local.year - 2, base_local.year + 6):
        cycle_start = _month_start(year, start_month, zone)
        for offset in range(span_months, 96 + span_months, span_months):
            run_anchor = _add_months(cycle_start, offset)
            day = _cycle_run_day(schedule, run_anchor)
            candidates.append(_date_at_local_time(run_anchor.year, run_anchor.month, day, hour, minute, zone))
    return candidates


def calculate_next_run_dt(schedule: AuditReviewSchedule, reference_dt: datetime) -> datetime:
    """Return the next planner occurrence after reference_dt as an aware UTC datetime."""

    frequency = str(getattr(schedule, "frequency", "") or "").strip().upper()
    zone = _zone_info(getattr(schedule, "timezone", None))
    base_local = _schedule_base_local(schedule, reference_dt, zone)
    hour, minute = _parse_run_time(schedule)

    if frequency == "DAILY":
        candidate = _date_at_local_time(base_local.year, base_local.month, base_local.day, hour, minute, zone)
        if candidate <= base_local:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(UTC)

    if frequency == "WEEKLY":
        day_of_week = getattr(schedule, "day_of_week", None)
        if day_of_week is None:
            raise AuditReviewValidationError("WEEKLY schedules require day_of_week.")
        base_day = _date_at_local_time(base_local.year, base_local.month, base_local.day, hour, minute, zone)
        offset = (int(day_of_week) - _local_weekday_sunday_zero(base_day) + 7) % 7
        candidate = base_day + timedelta(days=offset)
        if candidate <= base_local:
            candidate = candidate + timedelta(days=7)
        return candidate.astimezone(UTC)

    if frequency == "MONTHLY":
        month_cursor = _month_start(base_local.year, base_local.month, zone)
        for offset in range(0, 60):
            month_start = _add_months(month_cursor, offset)
            day = _monthly_candidate_day(schedule, month_start.year, month_start.month)
            candidate = _date_at_local_time(month_start.year, month_start.month, day, hour, minute, zone)
            if candidate <= base_local:
                continue
            if _monthly_review_range_for_reference(schedule, candidate, zone) is None:
                continue
            return candidate.astimezone(UTC)
        raise AuditReviewValidationError("Unable to calculate next MONTHLY schedule run.")

    if frequency == "QUARTERLY":
        candidates = _cycle_run_candidates(
            schedule,
            base_local,
            span_months=3,
            expected_calendar_cycle_type=CYCLE_TYPE_CALENDAR_QUARTER,
            expected_custom_cycle_type=CYCLE_TYPE_CUSTOM_QUARTER,
            zone=zone,
        )
        schedule_start_day = _schedule_start_local_day(schedule, zone)
        for candidate in sorted(candidates):
            if candidate <= base_local:
                continue
            if schedule_start_day is not None:
                _, candidate_review_end = _previous_calendar_quarter_range(candidate)
                if candidate_review_end < schedule_start_day:
                    continue
            return candidate.astimezone(UTC)
        raise AuditReviewValidationError("Unable to calculate next QUARTERLY schedule run.")

    if frequency == "HALF_YEARLY":
        candidates = _cycle_run_candidates(
            schedule,
            base_local,
            span_months=6,
            expected_calendar_cycle_type=CYCLE_TYPE_CALENDAR_HALF_YEAR,
            expected_custom_cycle_type=CYCLE_TYPE_CUSTOM_SIX_MONTH,
            zone=zone,
        )
        candidate = _first_local_candidate_after(candidates, base_local)
        if candidate is None:
            raise AuditReviewValidationError("Unable to calculate next HALF_YEARLY schedule run.")
        return candidate.astimezone(UTC)

    if frequency == "ANNUAL":
        cycle_type = str(getattr(schedule, "cycle_type", "") or "").strip().upper()
        if cycle_type not in {CYCLE_TYPE_CALENDAR_YEAR, CYCLE_TYPE_FISCAL_YEAR}:
            raise AuditReviewValidationError("ANNUAL schedules require a valid cycle_type.")
        run_month = (
            getattr(schedule, "fiscal_year_start_month", None)
            if cycle_type == CYCLE_TYPE_FISCAL_YEAR
            else 1
        )
        if run_month is None:
            raise AuditReviewValidationError("ANNUAL schedules require run month.")
        month = max(1, min(int(run_month), 12))
        day = 1
        candidates = [
            _date_at_local_time(year, month, _clamped_day(year, month, day), hour, minute, zone)
            for year in range(base_local.year - 1, base_local.year + 6)
        ]
        schedule_start_day = _schedule_start_local_day(schedule, zone)
        for candidate in sorted(candidates):
            if candidate <= base_local:
                continue
            if schedule_start_day is not None:
                _, candidate_review_end = _previous_annual_range(schedule, candidate)
                if candidate_review_end < schedule_start_day:
                    continue
            return candidate.astimezone(UTC)
        raise AuditReviewValidationError("Unable to calculate next ANNUAL schedule run.")

    raise AuditReviewValidationError("Unsupported audit review schedule frequency.", data={"frequency": frequency})


def _next_run_after(schedule: AuditReviewSchedule, reference_dt: datetime) -> datetime:
    return calculate_next_run_dt(schedule, reference_dt)


def _next_run_from_frequency_reference(
    schedule: AuditReviewSchedule,
    reference_dt: datetime,
    now: datetime,
) -> datetime:
    return calculate_next_run_dt(schedule, max(_to_utc(reference_dt), _to_utc(now)))


def _validate_final_schedule_planner_config(schedule: AuditReviewSchedule) -> None:
    frequency = str(getattr(schedule, "frequency", "") or "").strip().upper()
    run_time = str(getattr(schedule, "run_time", "") or "").strip()

    if frequency == "WEEKLY":
        if not run_time:
            raise AuditReviewValidationError("WEEKLY schedules require run_time.")
        if getattr(schedule, "day_of_week", None) is None:
            raise AuditReviewValidationError("WEEKLY schedules require day_of_week.")
    elif frequency == "MONTHLY":
        pass
    elif frequency == "QUARTERLY":
        if getattr(schedule, "cycle_type", None) not in {CYCLE_TYPE_CALENDAR_QUARTER, CYCLE_TYPE_CUSTOM_QUARTER}:
            raise AuditReviewValidationError("QUARTERLY schedules require a valid cycle_type.")
        if getattr(schedule, "run_timing", None) not in {RUN_TIMING_FIRST_DAY_AFTER_PERIOD_END, RUN_TIMING_CUSTOM_RUN_DAY}:
            raise AuditReviewValidationError("QUARTERLY schedules require a valid run_timing.")
        if schedule.cycle_type == CYCLE_TYPE_CUSTOM_QUARTER and getattr(schedule, "custom_cycle_start_month", None) is None:
            raise AuditReviewValidationError("CUSTOM_QUARTER_CYCLE schedules require custom_cycle_start_month.")
    elif frequency == "HALF_YEARLY":
        if getattr(schedule, "cycle_type", None) not in {CYCLE_TYPE_CALENDAR_HALF_YEAR, CYCLE_TYPE_CUSTOM_SIX_MONTH}:
            raise AuditReviewValidationError("HALF_YEARLY schedules require a valid cycle_type.")
        if getattr(schedule, "run_timing", None) not in {RUN_TIMING_FIRST_DAY_AFTER_PERIOD_END, RUN_TIMING_CUSTOM_RUN_DAY}:
            raise AuditReviewValidationError("HALF_YEARLY schedules require a valid run_timing.")
        if schedule.cycle_type == CYCLE_TYPE_CUSTOM_SIX_MONTH and getattr(schedule, "custom_cycle_start_month", None) is None:
            raise AuditReviewValidationError("CUSTOM_SIX_MONTH_CYCLE schedules require custom_cycle_start_month.")
    elif frequency == "ANNUAL":
        if getattr(schedule, "cycle_type", None) not in {CYCLE_TYPE_CALENDAR_YEAR, CYCLE_TYPE_FISCAL_YEAR}:
            raise AuditReviewValidationError("ANNUAL schedules require a valid cycle_type.")
        if schedule.cycle_type == CYCLE_TYPE_FISCAL_YEAR and getattr(schedule, "fiscal_year_start_month", None) is None:
            raise AuditReviewValidationError("FISCAL_YEAR schedules require fiscal_year_start_month.")
    elif frequency != "DAILY":
        raise AuditReviewValidationError("Unsupported audit review schedule frequency.", data={"frequency": frequency})

    _parse_run_time(schedule)


def _review_window_days(schedule: AuditReviewSchedule) -> int:
    if schedule.review_window_days is not None:
        return min(schedule.review_window_days, MAX_REVIEW_WINDOW_DAYS)
    if schedule.frequency == "DAILY":
        return DEFAULT_DAILY_REVIEW_WINDOW_DAYS
    if schedule.frequency == "WEEKLY":
        return 7
    if schedule.frequency == "QUARTERLY":
        return 90
    if schedule.frequency == "HALF_YEARLY":
        return 182
    if schedule.frequency == "ANNUAL":
        return 365
    return DEFAULT_REVIEW_WINDOW_DAYS


def _schedule_audit_retrieval_mode(schedule: AuditReviewSchedule) -> str:
    frequency = str(getattr(schedule, "frequency", "") or "").strip().upper()
    if frequency == "QUARTERLY":
        return AUDIT_RETRIEVAL_MODE_AUTO
    configured = str(getattr(schedule, "audit_retrieval_mode", "") or "").strip().upper()
    has_custom_range = (
        getattr(schedule, "custom_audit_start_dt", None) is not None
        and getattr(schedule, "custom_audit_end_dt", None) is not None
    )
    if configured == AUDIT_RETRIEVAL_MODE_CUSTOM or has_custom_range:
        return AUDIT_RETRIEVAL_MODE_CUSTOM
    if frequency in {"DAILY", "MONTHLY"}:
        return AUDIT_RETRIEVAL_MODE_AUTO
    if configured:
        return configured
    if frequency == "WEEKLY":
        return AUDIT_RETRIEVAL_MODE_SINCE_LAST_SUCCESSFUL
    return AUDIT_RETRIEVAL_MODE_AUTO


def _payload_audit_retrieval_mode(
    frequency: str | None,
    audit_retrieval_mode: str | None,
    custom_audit_start_dt: datetime | None,
    custom_audit_end_dt: datetime | None,
) -> str | None:
    if str(frequency or "").strip().upper() == "QUARTERLY":
        return AUDIT_RETRIEVAL_MODE_AUTO
    configured = str(audit_retrieval_mode or "").strip().upper()
    if configured == AUDIT_RETRIEVAL_MODE_CUSTOM or custom_audit_start_dt is not None or custom_audit_end_dt is not None:
        return AUDIT_RETRIEVAL_MODE_CUSTOM
    if str(frequency or "").strip().upper() in {"DAILY", "MONTHLY"}:
        return AUDIT_RETRIEVAL_MODE_AUTO
    return configured or audit_retrieval_mode


def _payload_end_condition(
    frequency: str | None,
    schedule_end_dt: datetime | None,
    end_condition: str | None,
    end_after_runs: int | None,
) -> str:
    if schedule_end_dt is not None:
        return END_CONDITION_END_ON_DATE
    configured = str(end_condition or "").strip().upper()
    if (
        str(frequency or "").strip().upper() != "DAILY"
        and configured == END_CONDITION_END_AFTER_RUNS
        and end_after_runs is not None
    ):
        return END_CONDITION_END_AFTER_RUNS
    return END_CONDITION_NO_END_DATE


def _month_start(year: int, month: int, zone: tzinfo) -> datetime:
    return datetime(year, month, 1, 0, 0, 0, tzinfo=zone)


def _local_day_start(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _local_day_end(value: datetime) -> datetime:
    return value.replace(hour=23, minute=59, second=59, microsecond=0)


def _schedule_start_local_day(schedule: AuditReviewSchedule, zone: tzinfo) -> datetime | None:
    schedule_start_dt = getattr(schedule, "schedule_start_dt", None)
    if schedule_start_dt is None:
        return None
    return _local_day_start(_to_utc(schedule_start_dt).astimezone(zone))


def _previous_calendar_month_range(reference_local: datetime) -> tuple[datetime, datetime]:
    first_this_month = _month_start(reference_local.year, reference_local.month, reference_local.tzinfo or UTC)
    previous_month_end = first_this_month - timedelta(seconds=1)
    previous_month_start = _month_start(
        previous_month_end.year,
        previous_month_end.month,
        reference_local.tzinfo or UTC,
    )
    return previous_month_start, previous_month_end


def _clamp_monthly_range_to_schedule_start(
    schedule: AuditReviewSchedule,
    start_local: datetime,
    end_local: datetime,
    zone: tzinfo,
) -> tuple[datetime, datetime] | None:
    schedule_start_day = _schedule_start_local_day(schedule, zone)
    if schedule_start_day is None:
        return start_local, end_local
    if end_local < schedule_start_day:
        return None
    return max(start_local, schedule_start_day), end_local


def _monthly_review_range_for_reference(
    schedule: AuditReviewSchedule,
    reference_local: datetime,
    zone: tzinfo,
) -> tuple[datetime, datetime] | None:
    start_local, end_local = _previous_calendar_month_range(reference_local)
    return _clamp_monthly_range_to_schedule_start(schedule, start_local, end_local, zone)


def _previous_calendar_quarter_range(reference_local: datetime) -> tuple[datetime, datetime]:
    current_quarter_start_month = ((reference_local.month - 1) // 3) * 3 + 1
    current_quarter_start = _month_start(reference_local.year, current_quarter_start_month, reference_local.tzinfo or UTC)
    previous_quarter_end = current_quarter_start - timedelta(seconds=1)
    previous_quarter_start_month = ((previous_quarter_end.month - 1) // 3) * 3 + 1
    previous_quarter_start = _month_start(
        previous_quarter_end.year,
        previous_quarter_start_month,
        reference_local.tzinfo or UTC,
    )
    return previous_quarter_start, previous_quarter_end


def _previous_calendar_half_year_range(reference_local: datetime) -> tuple[datetime, datetime]:
    zone = reference_local.tzinfo or UTC
    current_start_month = 1 if reference_local.month <= 6 else 7
    current_start = _month_start(reference_local.year, current_start_month, zone)
    previous_end = current_start - timedelta(seconds=1)
    previous_start_month = 1 if previous_end.month <= 6 else 7
    previous_start = _month_start(previous_end.year, previous_start_month, zone)
    return previous_start, previous_end


def _previous_custom_cycle_range(reference_local: datetime, start_month: int | None, span_months: int) -> tuple[datetime, datetime]:
    zone = reference_local.tzinfo or UTC
    normalized_start_month = max(1, min(int(start_month or 1), 12))
    cycle_starts: list[datetime] = []
    for year in range(reference_local.year - 2, reference_local.year + 2):
        cycle_start = _month_start(year, normalized_start_month, zone)
        while cycle_start.year <= reference_local.year + 1:
            cycle_starts.append(cycle_start)
            cycle_start = _add_months(cycle_start, span_months)
    current_start = max((item for item in cycle_starts if item <= reference_local), default=None)
    if current_start is None:
        current_start = _month_start(reference_local.year, normalized_start_month, zone)
    previous_start = _add_months(current_start, -span_months)
    return previous_start, current_start - timedelta(seconds=1)


def _custom_cycle_start_containing(reference_local: datetime, start_month: int | None, span_months: int) -> datetime:
    zone = reference_local.tzinfo or UTC
    normalized_start_month = max(1, min(int(start_month or 1), 12))
    cycle_starts: list[datetime] = []
    for year in range(reference_local.year - 2, reference_local.year + 2):
        cycle_start = _month_start(year, normalized_start_month, zone)
        while cycle_start.year <= reference_local.year + 1:
            cycle_starts.append(cycle_start)
            cycle_start = _add_months(cycle_start, span_months)
    return max((item for item in cycle_starts if item <= reference_local), default=_month_start(reference_local.year, normalized_start_month, zone))


def _half_year_period_start_containing(schedule: AuditReviewSchedule, reference_local: datetime) -> datetime:
    zone = reference_local.tzinfo or UTC
    if getattr(schedule, "cycle_type", None) == CYCLE_TYPE_CUSTOM_SIX_MONTH:
        return _custom_cycle_start_containing(reference_local, schedule.custom_cycle_start_month, 6)
    start_month = 1 if reference_local.month <= 6 else 7
    return _month_start(reference_local.year, start_month, zone)


def _annual_period_start_containing(schedule: AuditReviewSchedule, reference_local: datetime) -> datetime:
    zone = reference_local.tzinfo or UTC
    fiscal_start_month = schedule.fiscal_year_start_month or 1
    if getattr(schedule, "cycle_type", None) == CYCLE_TYPE_FISCAL_YEAR and fiscal_start_month != 1:
        start_year = reference_local.year if reference_local.month >= fiscal_start_month else reference_local.year - 1
        return _month_start(start_year, fiscal_start_month, zone)
    return _month_start(reference_local.year, 1, zone)


def _previous_annual_range(schedule: AuditReviewSchedule, reference_local: datetime) -> tuple[datetime, datetime]:
    zone = reference_local.tzinfo or UTC
    fiscal_start_month = schedule.fiscal_year_start_month or 1
    if getattr(schedule, "cycle_type", None) == CYCLE_TYPE_FISCAL_YEAR and fiscal_start_month != 1:
        current_start_year = reference_local.year if reference_local.month >= fiscal_start_month else reference_local.year - 1
        current_start = _month_start(current_start_year, fiscal_start_month, zone)
        previous_start = _month_start(current_start_year - 1, fiscal_start_month, zone)
        return previous_start, current_start - timedelta(seconds=1)
    current_year_start = _month_start(reference_local.year, 1, zone)
    return _month_start(reference_local.year - 1, 1, zone), current_year_start - timedelta(seconds=1)


async def _audit_retrieval_range(
    db: AsyncSession,
    schedule: AuditReviewSchedule,
    reference_dt: datetime,
    *,
    use_last_successful_anchor: bool = True,
) -> tuple[datetime, datetime, str]:
    mode = _schedule_audit_retrieval_mode(schedule)
    reference_utc = _to_utc(reference_dt)
    zone = _zone_info(schedule.timezone)
    reference_local = reference_utc.astimezone(zone)

    if mode == AUDIT_RETRIEVAL_MODE_CUSTOM:
        if schedule.custom_audit_start_dt is None or schedule.custom_audit_end_dt is None:
            raise AuditReviewValidationError(
                "Custom audit retrieval mode requires custom audit start and end dates.",
                data={"schedule_id": str(schedule.schedule_id)},
            )
        start = _to_utc(schedule.custom_audit_start_dt)
        end = _to_utc(schedule.custom_audit_end_dt)
        if end < start:
            raise AuditReviewValidationError("custom_audit_start_dt must be before or equal to custom_audit_end_dt")
        if schedule.frequency == "DAILY":
            next_run_dt = _to_utc(getattr(schedule, "next_run_dt", None) or reference_utc)
            if end > next_run_dt:
                raise AuditReviewValidationError("custom_audit_end_dt must not be after the next run time")
            now = _utc_now()
            if start > now or end > now:
                raise AuditReviewValidationError("custom audit period must not be in the future")
        return start, end, mode

    if mode == AUDIT_RETRIEVAL_MODE_SINCE_LAST_SUCCESSFUL:
        review_end_dt = reference_utc
        review_start_dt = await _latest_completed_review_end(db, schedule) if use_last_successful_anchor else None
        if review_start_dt is None or review_start_dt >= review_end_dt:
            review_start_dt = review_end_dt - timedelta(days=_review_window_days(schedule))
        return _to_utc(review_start_dt), review_end_dt, mode

    if schedule.frequency == "DAILY":
        target_day = _local_day_start(reference_local) - timedelta(days=1)
        return target_day.astimezone(UTC), _local_day_end(target_day).astimezone(UTC), mode

    if schedule.frequency == "WEEKLY":
        return reference_utc - timedelta(days=7), reference_utc, mode

    if schedule.frequency == "MONTHLY":
        monthly_range = _monthly_review_range_for_reference(schedule, reference_local, zone)
        if monthly_range is None:
            next_reference = calculate_next_run_dt(schedule, reference_utc)
            reference_local = next_reference.astimezone(zone)
            monthly_range = _monthly_review_range_for_reference(schedule, reference_local, zone)
        if monthly_range is None:
            raise AuditReviewValidationError("Unable to calculate MONTHLY audit retrieval range after schedule start.")
        start_local, end_local = monthly_range
        return start_local.astimezone(UTC), end_local.astimezone(UTC), mode

    if schedule.frequency == "QUARTERLY":
        start_local, end_local = _previous_calendar_quarter_range(reference_local)
        return start_local.astimezone(UTC), end_local.astimezone(UTC), mode

    if schedule.frequency == "HALF_YEARLY":
        if schedule.cycle_type == "CUSTOM_SIX_MONTH_CYCLE":
            start_local, end_local = _previous_custom_cycle_range(reference_local, schedule.custom_cycle_start_month, 6)
        else:
            start_local, end_local = _previous_calendar_half_year_range(reference_local)
        return start_local.astimezone(UTC), end_local.astimezone(UTC), mode

    if schedule.frequency == "ANNUAL":
        start_local, end_local = _previous_annual_range(schedule, reference_local)
        return start_local.astimezone(UTC), end_local.astimezone(UTC), mode

    review_end_dt = reference_utc
    return review_end_dt - timedelta(days=_review_window_days(schedule)), review_end_dt, mode


def _clamp_review_start_for_veeva(review_start_dt: datetime, reference_dt: datetime) -> datetime:
    configured_days = getattr(get_settings(), "VEEVA_AUDIT_LOOKBACK_DAYS", DEFAULT_VEEVA_AUDIT_LOOKBACK_DAYS)
    try:
        lookback_days = max(1, min(int(configured_days), MAX_REVIEW_WINDOW_DAYS))
    except (TypeError, ValueError):
        lookback_days = DEFAULT_VEEVA_AUDIT_LOOKBACK_DAYS
    oldest_allowed = _to_utc(reference_dt) - timedelta(days=lookback_days) + VEEVA_AUDIT_LOOKBACK_SAFETY_MARGIN
    return max(_to_utc(review_start_dt), oldest_allowed)


def _next_custom_audit_range_after_run(
    schedule: AuditReviewSchedule,
    review_start_dt: datetime,
    review_end_dt: datetime,
) -> tuple[datetime, datetime]:
    next_start = _to_utc(review_end_dt)
    next_end = _to_utc(getattr(schedule, "next_run_dt", None) or next_start)
    if next_end <= next_start:
        next_end = calculate_next_run_dt(schedule, next_start)
    if next_end <= next_start:
        next_end = _add_frequency(next_start, schedule.frequency)
    return next_start, _to_utc(next_end)


def _business_start_hour(schedule: AuditReviewSchedule) -> int:
    return DEFAULT_BUSINESS_START_HOUR


def _business_end_hour(schedule: AuditReviewSchedule) -> int:
    return DEFAULT_BUSINESS_END_HOUR


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _to_utc(parsed)


def _schedule_summary(schedule: AuditReviewSchedule) -> dict[str, Any]:
    return {
        "schedule_id": str(schedule.schedule_id),
        "asset_id": str(schedule.asset_id),
        "audit_trail_type": schedule.audit_trail_type,
        "review_scope": schedule.review_scope,
        "selected_audit_trail_types": _schedule_selected_types(schedule),
        "frequency": schedule.frequency,
        "review_window_days": schedule.review_window_days,
        "schedule_start_dt": _iso_utc(schedule.schedule_start_dt),
        "schedule_end_dt": _iso_utc(schedule.schedule_end_dt),
        "end_condition": schedule.end_condition,
        "end_after_runs": schedule.end_after_runs,
        "run_time": schedule.run_time,
        "day_of_week": schedule.day_of_week,
        "day_of_month": schedule.day_of_month,
        "use_last_day_of_month": schedule.use_last_day_of_month,
        "cycle_type": schedule.cycle_type,
        "run_timing": schedule.run_timing,
        "run_month": schedule.run_month,
        "custom_cycle_start_month": schedule.custom_cycle_start_month,
        "fiscal_year_start_month": schedule.fiscal_year_start_month,
        "audit_retrieval_mode": _schedule_audit_retrieval_mode(schedule),
        "custom_audit_start_dt": _iso_utc(schedule.custom_audit_start_dt),
        "custom_audit_end_dt": _iso_utc(schedule.custom_audit_end_dt),
        "timezone": schedule.timezone,
        "business_start_hour": _business_start_hour(schedule),
        "business_end_hour": _business_end_hour(schedule),
        "vault_dns": schedule.vault_dns,
        "veeva_instance_name": schedule.veeva_instance_name,
        "veeva_app_name": schedule.veeva_app_name,
        "next_run_dt": _iso_utc(schedule.next_run_dt),
        "last_run_dt": _iso_utc(schedule.last_run_dt),
    }


def _build_schedule_response(schedule: AuditReviewSchedule) -> AuditReviewScheduleResponse:
    return AuditReviewScheduleResponse(
        schedule_id=schedule.schedule_id,
        asset_id=schedule.asset_id,
        enabled=schedule.enabled,
        vault_dns=schedule.vault_dns,
        veeva_instance_name=schedule.veeva_instance_name,
        veeva_app_name=schedule.veeva_app_name,
        audit_trail_type=schedule.audit_trail_type,
        review_scope=schedule.review_scope,
        selected_audit_trail_types=_schedule_selected_types(schedule),
        frequency=schedule.frequency,
        review_window_days=schedule.review_window_days,
        next_run_dt=schedule.next_run_dt,
        schedule_start_dt=schedule.schedule_start_dt,
        schedule_end_dt=schedule.schedule_end_dt,
        end_condition=schedule.end_condition,
        end_after_runs=schedule.end_after_runs,
        run_time=schedule.run_time,
        day_of_week=schedule.day_of_week,
        day_of_month=schedule.day_of_month,
        use_last_day_of_month=schedule.use_last_day_of_month,
        cycle_type=schedule.cycle_type,
        run_timing=schedule.run_timing,
        run_month=schedule.run_month,
        custom_cycle_start_month=schedule.custom_cycle_start_month,
        fiscal_year_start_month=schedule.fiscal_year_start_month,
        audit_retrieval_mode=_schedule_audit_retrieval_mode(schedule),
        custom_audit_start_dt=schedule.custom_audit_start_dt,
        custom_audit_end_dt=schedule.custom_audit_end_dt,
        last_run_dt=schedule.last_run_dt,
        last_job_id=schedule.last_job_id,
        timezone=schedule.timezone,
        business_start_hour=schedule.business_start_hour,
        business_end_hour=schedule.business_end_hour,
        created_by=schedule.created_by,
        created_dt=schedule.created_dt,
        modified_by=schedule.modified_by,
        modified_dt=schedule.modified_dt,
    )


def _build_run_response(run: AuditReviewScheduleRun) -> AuditReviewScheduleRunResponse:
    return AuditReviewScheduleRunResponse(
        run_id=run.run_id,
        schedule_id=run.schedule_id,
        asset_id=run.asset_id,
        job_id=run.job_id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        message=run.message,
        error_message=run.error_message,
        run_summary_json=run.run_summary_json or {},
    )


async def _require_asset(db: AsyncSession, asset_id: uuid.UUID) -> Asset:
    result = await db.execute(select(Asset).where(Asset.asset_uuid == asset_id))
    asset = result.scalars().first()
    if asset is None:
        raise AuditReviewNotFoundError("Asset not found")
    return asset


async def _require_schedule(db: AsyncSession, schedule_id: uuid.UUID) -> AuditReviewSchedule:
    result = await db.execute(select(AuditReviewSchedule).where(AuditReviewSchedule.schedule_id == schedule_id))
    schedule = result.scalars().first()
    if schedule is None:
        raise AuditReviewNotFoundError("Audit review schedule not found")
    return schedule


async def _require_run(db: AsyncSession, run_id: uuid.UUID) -> AuditReviewScheduleRun:
    result = await db.execute(select(AuditReviewScheduleRun).where(AuditReviewScheduleRun.run_id == run_id))
    run = result.scalars().first()
    if run is None:
        raise AuditReviewNotFoundError("Audit review schedule run not found")
    return run


def _summary_selected_types(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _run_summary_matches_schedule(schedule: AuditReviewSchedule, summary: Any) -> bool:
    if not isinstance(summary, dict):
        return False
    schedule_summary = summary.get("schedule") if isinstance(summary.get("schedule"), dict) else {}
    summary_scope = str(summary.get("review_scope") or schedule_summary.get("review_scope") or "").strip().upper()
    summary_selected = _summary_selected_types(
        summary.get("selected_audit_trail_types") or schedule_summary.get("selected_audit_trail_types")
    )
    summary_audit_type = str(schedule_summary.get("audit_trail_type") or "").strip()

    current_selected = _schedule_selected_types(schedule)
    if not summary_selected and summary_audit_type:
        summary_selected = [summary_audit_type]

    return summary_scope == str(schedule.review_scope or "").strip().upper() and summary_selected == current_selected


def _job_matches_schedule(schedule: AuditReviewSchedule, job: AuditReviewJob | None) -> bool:
    if job is None:
        return False
    job_selected = job.selected_audit_trail_types_json
    if isinstance(job_selected, list):
        selected = [str(item).strip() for item in job_selected if str(item).strip()]
    else:
        selected = []
    if not selected and job.audit_trail_type:
        selected = [job.audit_trail_type]
    return (
        str(job.review_scope or "").strip().upper() == str(schedule.review_scope or "").strip().upper()
        and selected == _schedule_selected_types(schedule)
    )


async def _latest_completed_review_end(db: AsyncSession, schedule: AuditReviewSchedule) -> datetime | None:
    result = await db.execute(
        select(AuditReviewScheduleRun.run_summary_json)
        .where(
            AuditReviewScheduleRun.schedule_id == schedule.schedule_id,
            AuditReviewScheduleRun.status == AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED,
        )
        .order_by(AuditReviewScheduleRun.completed_at.desc().nulls_last(), AuditReviewScheduleRun.started_at.desc())
        .limit(25)
    )
    for summary in result.scalars().all():
        if not _run_summary_matches_schedule(schedule, summary):
            continue
        parsed = _parse_iso_datetime(summary.get("review_end_dt"))
        if parsed is not None:
            return parsed

    if schedule.last_job_id is None:
        return None

    job_result = await db.execute(
        select(AuditReviewJob).where(
            AuditReviewJob.job_id == schedule.last_job_id,
            AuditReviewJob.status != AUDIT_REVIEW_STATUS_FAILED,
        )
    )
    last_job = job_result.scalars().first()
    if not _job_matches_schedule(schedule, last_job):
        return None
    return _to_utc(last_job.review_end_dt) if last_job.review_end_dt is not None else None


async def _find_matching_schedule(
    db: AsyncSession,
    asset_id: uuid.UUID,
    payload: AuditReviewScheduleUpsertRequest,
) -> AuditReviewSchedule | None:
    review_scope, selected_types = _resolve_schedule_selection(
        payload.review_scope,
        payload.selected_audit_trail_types,
        payload.audit_trail_type,
    )
    result = await db.execute(
        select(AuditReviewSchedule)
        .where(
            AuditReviewSchedule.asset_id == asset_id,
            AuditReviewSchedule.audit_trail_type == (selected_types[0] if selected_types else payload.audit_trail_type),
            AuditReviewSchedule.review_scope == review_scope,
            AuditReviewSchedule.vault_dns.isnot_distinct_from(payload.vault_dns),
            AuditReviewSchedule.veeva_instance_name.isnot_distinct_from(payload.veeva_instance_name),
            AuditReviewSchedule.veeva_app_name.isnot_distinct_from(payload.veeva_app_name),
        )
        .order_by(AuditReviewSchedule.created_dt.desc(), AuditReviewSchedule.schedule_id.desc())
        .limit(1)
    )
    return result.scalars().first()


def _apply_schedule_values(
    schedule: AuditReviewSchedule,
    payload: AuditReviewScheduleUpsertRequest,
    *,
    actor: str | None,
    now: datetime,
) -> None:
    review_scope, selected_types = _resolve_schedule_selection(
        payload.review_scope,
        payload.selected_audit_trail_types,
        payload.audit_trail_type,
    )
    schedule.enabled = payload.enabled
    schedule.vault_dns = payload.vault_dns
    schedule.veeva_instance_name = payload.veeva_instance_name
    schedule.veeva_app_name = payload.veeva_app_name
    schedule.audit_trail_type = selected_types[0] if selected_types else DEFAULT_AUDIT_TRAIL_TYPE
    schedule.review_scope = review_scope
    schedule.selected_audit_trail_types_json = selected_types
    schedule.frequency = payload.frequency
    schedule.review_window_days = payload.review_window_days
    frequency_value = str(payload.frequency or "").strip().upper()
    schedule.schedule_start_dt = payload.schedule_start_dt
    schedule.schedule_end_dt = payload.schedule_end_dt
    schedule.end_condition = _payload_end_condition(
        payload.frequency,
        schedule.schedule_end_dt,
        payload.end_condition,
        payload.end_after_runs,
    )
    schedule.end_after_runs = payload.end_after_runs if schedule.end_condition == END_CONDITION_END_AFTER_RUNS else None
    schedule.run_time = payload.run_time
    schedule.day_of_week = payload.day_of_week
    schedule.day_of_month = 1 if frequency_value == "MONTHLY" else None
    schedule.use_last_day_of_month = False if frequency_value == "MONTHLY" else payload.use_last_day_of_month
    schedule.cycle_type = CYCLE_TYPE_CALENDAR_QUARTER if frequency_value == "QUARTERLY" else payload.cycle_type
    schedule.run_timing = RUN_TIMING_FIRST_DAY_AFTER_PERIOD_END if frequency_value == "QUARTERLY" else payload.run_timing
    schedule.run_month = 1 if frequency_value == "ANNUAL" and payload.cycle_type == CYCLE_TYPE_CALENDAR_YEAR else payload.run_month
    schedule.custom_cycle_start_month = payload.custom_cycle_start_month
    schedule.fiscal_year_start_month = payload.fiscal_year_start_month
    schedule.audit_retrieval_mode = _payload_audit_retrieval_mode(
        payload.frequency,
        payload.audit_retrieval_mode,
        payload.custom_audit_start_dt,
        payload.custom_audit_end_dt,
    )
    schedule.custom_audit_start_dt = None if frequency_value == "QUARTERLY" else payload.custom_audit_start_dt
    schedule.custom_audit_end_dt = None if frequency_value == "QUARTERLY" else payload.custom_audit_end_dt
    schedule.timezone = payload.timezone or DEFAULT_SCHEDULE_TIMEZONE
    schedule.business_start_hour = None
    schedule.business_end_hour = None
    schedule.modified_by = actor
    schedule.modified_dt = now


def _validate_final_business_hours(schedule: AuditReviewSchedule) -> None:
    if schedule.business_start_hour is None or schedule.business_end_hour is None:
        return
    if schedule.business_end_hour <= schedule.business_start_hour:
        raise AuditReviewValidationError("business_end_hour must be after business_start_hour")


def _validate_final_schedule_config(schedule: AuditReviewSchedule) -> None:
    _validate_final_schedule_planner_config(schedule)
    if schedule.schedule_start_dt is not None and schedule.schedule_end_dt is not None:
        if _to_utc(schedule.schedule_end_dt) < _to_utc(schedule.schedule_start_dt):
            raise AuditReviewValidationError("schedule_end_dt must be on or after schedule_start_dt")
        if str(getattr(schedule, "frequency", "") or "").strip().upper() == "QUARTERLY":
            zone = _zone_info(getattr(schedule, "timezone", None))
            schedule_start_day = _schedule_start_local_day(schedule, zone)
            end_review_start, _ = _previous_calendar_quarter_range(_to_utc(schedule.schedule_end_dt).astimezone(zone))
            if schedule_start_day is not None and end_review_start < schedule_start_day:
                raise AuditReviewValidationError(
                    "schedule_end_dt must represent the same or a later quarterly review period than schedule_start_dt"
                )
        if str(getattr(schedule, "frequency", "") or "").strip().upper() == "HALF_YEARLY":
            zone = _zone_info(getattr(schedule, "timezone", None))
            schedule_start_day = _schedule_start_local_day(schedule, zone)
            end_reference = _to_utc(schedule.schedule_end_dt).astimezone(zone)
            if getattr(schedule, "cycle_type", None) == CYCLE_TYPE_CUSTOM_SIX_MONTH:
                end_review_start, _ = _previous_custom_cycle_range(end_reference, schedule.custom_cycle_start_month, 6)
            else:
                end_review_start, _ = _previous_calendar_half_year_range(end_reference)
            if schedule_start_day is not None:
                start_review_start = _half_year_period_start_containing(schedule, schedule_start_day)
                if end_review_start < start_review_start:
                    raise AuditReviewValidationError(
                        "schedule_end_dt must represent the same or a later half-year review period than schedule_start_dt"
                    )
        if str(getattr(schedule, "frequency", "") or "").strip().upper() == "ANNUAL":
            zone = _zone_info(getattr(schedule, "timezone", None))
            schedule_start_day = _schedule_start_local_day(schedule, zone)
            end_reference = _to_utc(schedule.schedule_end_dt).astimezone(zone)
            end_review_start, _ = _previous_annual_range(schedule, end_reference)
            if schedule_start_day is not None:
                start_review_start = _annual_period_start_containing(schedule, schedule_start_day)
                if end_review_start < start_review_start:
                    raise AuditReviewValidationError(
                        "Schedule ending year must be the same as or after the start reviewing year."
                    )
    if schedule.end_condition == END_CONDITION_END_ON_DATE and schedule.schedule_end_dt is None:
        raise AuditReviewValidationError("schedule_end_dt is required when end_condition is END_ON_DATE")
    if schedule.end_condition == END_CONDITION_END_AFTER_RUNS and schedule.end_after_runs is None:
        raise AuditReviewValidationError("end_after_runs is required when end_condition is END_AFTER_RUNS")
    if _schedule_audit_retrieval_mode(schedule) == AUDIT_RETRIEVAL_MODE_CUSTOM:
        if schedule.custom_audit_start_dt is None or schedule.custom_audit_end_dt is None:
            raise AuditReviewValidationError("Custom audit retrieval mode requires custom audit start and end dates.")
        if _to_utc(schedule.custom_audit_end_dt) < _to_utc(schedule.custom_audit_start_dt):
            raise AuditReviewValidationError("custom_audit_start_dt must be before or equal to custom_audit_end_dt")


async def upsert_audit_review_schedule(
    db: AsyncSession,
    asset_id: uuid.UUID,
    payload: AuditReviewScheduleUpsertRequest,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewScheduleResponse:
    await _require_asset(db, asset_id)
    now = _utc_now()
    actor = _current_user_actor_label(current_user)
    review_scope, selected_types = _resolve_schedule_selection(
        payload.review_scope,
        payload.selected_audit_trail_types,
        payload.audit_trail_type,
    )
    schedule = await _find_matching_schedule(db, asset_id, payload)
    if schedule is None:
        frequency_value = str(payload.frequency or "").strip().upper()
        schedule_end_dt = payload.schedule_end_dt
        end_condition = _payload_end_condition(
            payload.frequency,
            schedule_end_dt,
            payload.end_condition,
            payload.end_after_runs,
        )
        schedule = AuditReviewSchedule(
            asset_id=asset_id,
            enabled=payload.enabled,
            vault_dns=payload.vault_dns,
            veeva_instance_name=payload.veeva_instance_name,
            veeva_app_name=payload.veeva_app_name,
            audit_trail_type=selected_types[0] if selected_types else DEFAULT_AUDIT_TRAIL_TYPE,
            review_scope=review_scope,
            selected_audit_trail_types_json=selected_types,
            frequency=payload.frequency,
            review_window_days=payload.review_window_days,
            next_run_dt=now,
            schedule_start_dt=payload.schedule_start_dt,
            schedule_end_dt=schedule_end_dt,
            end_condition=end_condition,
            end_after_runs=payload.end_after_runs if end_condition == END_CONDITION_END_AFTER_RUNS else None,
            run_time=payload.run_time,
            day_of_week=payload.day_of_week,
            day_of_month=1 if frequency_value == "MONTHLY" else None,
            use_last_day_of_month=False if frequency_value == "MONTHLY" else payload.use_last_day_of_month,
            cycle_type=CYCLE_TYPE_CALENDAR_QUARTER if frequency_value == "QUARTERLY" else payload.cycle_type,
            run_timing=RUN_TIMING_FIRST_DAY_AFTER_PERIOD_END if frequency_value == "QUARTERLY" else payload.run_timing,
            run_month=1 if frequency_value == "ANNUAL" and payload.cycle_type == CYCLE_TYPE_CALENDAR_YEAR else payload.run_month,
            custom_cycle_start_month=payload.custom_cycle_start_month,
            fiscal_year_start_month=payload.fiscal_year_start_month,
            audit_retrieval_mode=_payload_audit_retrieval_mode(
                payload.frequency,
                payload.audit_retrieval_mode,
                payload.custom_audit_start_dt,
                payload.custom_audit_end_dt,
            ),
            custom_audit_start_dt=None if frequency_value == "QUARTERLY" else payload.custom_audit_start_dt,
            custom_audit_end_dt=None if frequency_value == "QUARTERLY" else payload.custom_audit_end_dt,
            timezone=payload.timezone or DEFAULT_SCHEDULE_TIMEZONE,
            business_start_hour=payload.business_start_hour,
            business_end_hour=payload.business_end_hour,
            created_by=actor,
            created_dt=now,
            modified_by=actor,
            modified_dt=now,
        )
        db.add(schedule)
    else:
        _apply_schedule_values(schedule, payload, actor=actor, now=now)

    _validate_final_business_hours(schedule)
    _validate_final_schedule_config(schedule)
    schedule.next_run_dt = calculate_next_run_dt(schedule, now)
    await db.commit()
    return _build_schedule_response(schedule)


async def list_audit_review_schedules_for_asset(
    db: AsyncSession,
    asset_id: uuid.UUID,
) -> list[AuditReviewScheduleResponse]:
    await _require_asset(db, asset_id)
    result = await db.execute(
        select(AuditReviewSchedule)
        .where(AuditReviewSchedule.asset_id == asset_id)
        .order_by(AuditReviewSchedule.created_dt.desc(), AuditReviewSchedule.schedule_id.desc())
    )
    return [_build_schedule_response(schedule) for schedule in result.scalars().all()]


async def update_audit_review_schedule(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    payload: AuditReviewSchedulePatchRequest,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewScheduleResponse:
    schedule = await _require_schedule(db, schedule_id)
    fields_set = payload.model_fields_set
    now = _utc_now()
    next_run_provided = "next_run_dt" in fields_set and payload.next_run_dt is not None
    planner_fields = {
        "frequency",
        "run_time",
        "day_of_week",
        "day_of_month",
        "use_last_day_of_month",
        "cycle_type",
        "run_timing",
        "run_month",
        "custom_cycle_start_month",
        "fiscal_year_start_month",
        "schedule_start_dt",
        "timezone",
    }
    planner_changed = bool(fields_set & planner_fields)

    if "enabled" in fields_set and payload.enabled is not None:
        schedule.enabled = payload.enabled
    if (
        "audit_trail_type" in fields_set
        or "review_scope" in fields_set
        or "selected_audit_trail_types" in fields_set
    ):
        review_scope, selected_types = _resolve_schedule_selection(
            payload.review_scope if "review_scope" in fields_set else schedule.review_scope,
            payload.selected_audit_trail_types
            if "selected_audit_trail_types" in fields_set
            else _schedule_selected_types(schedule),
            payload.audit_trail_type if payload.audit_trail_type is not None else schedule.audit_trail_type,
        )
        schedule.audit_trail_type = selected_types[0] if selected_types else DEFAULT_AUDIT_TRAIL_TYPE
        schedule.review_scope = review_scope
        schedule.selected_audit_trail_types_json = selected_types
    if "veeva_instance_name" in fields_set:
        schedule.veeva_instance_name = payload.veeva_instance_name
    if "veeva_app_name" in fields_set:
        schedule.veeva_app_name = payload.veeva_app_name
    if "vault_dns" in fields_set:
        schedule.vault_dns = payload.vault_dns
    if "frequency" in fields_set and payload.frequency is not None:
        schedule.frequency = payload.frequency
    if "review_window_days" in fields_set:
        schedule.review_window_days = payload.review_window_days
    if "next_run_dt" in fields_set and payload.next_run_dt is not None:
        schedule.next_run_dt = _to_utc(payload.next_run_dt)
    if "schedule_start_dt" in fields_set:
        schedule.schedule_start_dt = payload.schedule_start_dt
    if "schedule_end_dt" in fields_set:
        schedule.schedule_end_dt = payload.schedule_end_dt
    if "end_condition" in fields_set:
        schedule.end_condition = payload.end_condition
    if "end_after_runs" in fields_set:
        schedule.end_after_runs = payload.end_after_runs
    if fields_set & {"frequency", "schedule_end_dt", "end_condition", "end_after_runs"}:
        schedule.end_condition = _payload_end_condition(
            schedule.frequency,
            schedule.schedule_end_dt,
            schedule.end_condition,
            schedule.end_after_runs,
        )
        if schedule.end_condition != END_CONDITION_END_AFTER_RUNS:
            schedule.end_after_runs = None
    if "run_time" in fields_set:
        schedule.run_time = payload.run_time
    if "day_of_week" in fields_set:
        schedule.day_of_week = payload.day_of_week
    frequency_value = str(getattr(schedule, "frequency", "") or "").strip().upper()
    if "day_of_month" in fields_set:
        schedule.day_of_month = 1 if frequency_value == "MONTHLY" else None
    if "use_last_day_of_month" in fields_set:
        schedule.use_last_day_of_month = False if frequency_value == "MONTHLY" else payload.use_last_day_of_month
    if "cycle_type" in fields_set:
        schedule.cycle_type = payload.cycle_type
    if "run_timing" in fields_set:
        schedule.run_timing = payload.run_timing
    if "run_month" in fields_set:
        schedule.run_month = payload.run_month
    if "custom_cycle_start_month" in fields_set:
        schedule.custom_cycle_start_month = payload.custom_cycle_start_month
    if "fiscal_year_start_month" in fields_set:
        schedule.fiscal_year_start_month = payload.fiscal_year_start_month
    if frequency_value == "QUARTERLY":
        schedule.cycle_type = CYCLE_TYPE_CALENDAR_QUARTER
        schedule.run_timing = RUN_TIMING_FIRST_DAY_AFTER_PERIOD_END
        schedule.custom_cycle_start_month = None
        schedule.end_after_runs = None
    if frequency_value == "ANNUAL" and schedule.cycle_type == CYCLE_TYPE_CALENDAR_YEAR:
        schedule.run_month = 1
        schedule.fiscal_year_start_month = None
    if "audit_retrieval_mode" in fields_set:
        schedule.audit_retrieval_mode = payload.audit_retrieval_mode
        if payload.audit_retrieval_mode != AUDIT_RETRIEVAL_MODE_CUSTOM and (
            "custom_audit_start_dt" not in fields_set and "custom_audit_end_dt" not in fields_set
        ):
            schedule.custom_audit_start_dt = None
            schedule.custom_audit_end_dt = None
    if "custom_audit_start_dt" in fields_set:
        schedule.custom_audit_start_dt = payload.custom_audit_start_dt
    if "custom_audit_end_dt" in fields_set:
        schedule.custom_audit_end_dt = payload.custom_audit_end_dt
    if schedule.custom_audit_start_dt is not None or schedule.custom_audit_end_dt is not None:
        schedule.audit_retrieval_mode = AUDIT_RETRIEVAL_MODE_CUSTOM
    elif schedule.frequency == "DAILY":
        schedule.audit_retrieval_mode = AUDIT_RETRIEVAL_MODE_AUTO
    if frequency_value == "QUARTERLY":
        schedule.audit_retrieval_mode = AUDIT_RETRIEVAL_MODE_AUTO
        schedule.custom_audit_start_dt = None
        schedule.custom_audit_end_dt = None
    if "timezone" in fields_set and payload.timezone is not None:
        schedule.timezone = payload.timezone
    if "business_start_hour" in fields_set:
        schedule.business_start_hour = None
    if "business_end_hour" in fields_set:
        schedule.business_end_hour = None

    _validate_final_business_hours(schedule)
    _validate_final_schedule_config(schedule)
    if planner_changed:
        schedule.next_run_dt = calculate_next_run_dt(schedule, now)
    elif next_run_provided:
        schedule.next_run_dt = _to_utc(schedule.next_run_dt)
    schedule.modified_by = _current_user_actor_label(current_user)
    schedule.modified_dt = now
    await db.commit()
    return _build_schedule_response(schedule)


async def _create_skipped_run(
    db: AsyncSession,
    schedule: AuditReviewSchedule,
    *,
    message: str,
    summary: dict[str, Any] | None = None,
    job_id: uuid.UUID | None = None,
    advance_next_run: bool = False,
) -> AuditReviewScheduleRun:
    now = _utc_now()
    run = AuditReviewScheduleRun(
        schedule_id=schedule.schedule_id,
        asset_id=schedule.asset_id,
        job_id=job_id,
        status=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_SKIPPED,
        started_at=now,
        completed_at=now,
        message=message,
        error_message=None,
        run_summary_json={
            "schedule": _schedule_summary(schedule),
            "skipped_at": _iso_utc(now),
            "reason": message,
            **(summary or {}),
        },
    )
    db.add(run)
    if advance_next_run and _to_utc(schedule.next_run_dt) <= now:
        schedule.last_run_dt = now
        schedule.last_job_id = job_id or schedule.last_job_id
        schedule.next_run_dt = calculate_next_run_dt(schedule, now)
        schedule.modified_dt = now
    await db.commit()
    return run


async def _completed_schedule_run_count(db: AsyncSession, schedule_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(AuditReviewScheduleRun.run_id)).where(
            AuditReviewScheduleRun.schedule_id == schedule_id,
            AuditReviewScheduleRun.status == AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED,
        )
    )
    return int(result.scalar_one() or 0)


async def _start_schedule_execution(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    *,
    trigger_mode: str,
    due_only: bool,
) -> tuple[ScheduleExecution | None, AuditReviewScheduleRun | None]:
    now = _utc_now()
    result = await db.execute(
        select(AuditReviewSchedule)
        .where(AuditReviewSchedule.schedule_id == schedule_id)
        .with_for_update()
    )
    schedule = result.scalars().first()
    if schedule is None:
        raise AuditReviewNotFoundError("Audit review schedule not found")

    if due_only and not schedule.enabled:
        run = await _create_skipped_run(db, schedule, message="Schedule is disabled.")
        return None, run

    if due_only and _to_utc(schedule.next_run_dt) > now:
        run = await _create_skipped_run(db, schedule, message="Schedule is not due yet.")
        return None, run

    if due_only and schedule.schedule_start_dt is not None and _to_utc(schedule.schedule_start_dt) > now:
        run = await _create_skipped_run(db, schedule, message="Schedule has not reached its start date.")
        return None, run

    if due_only and schedule.schedule_end_dt is not None and schedule.end_condition != END_CONDITION_END_AFTER_RUNS:
        schedule_end_utc = _to_utc(schedule.schedule_end_dt)
        next_run_utc = _to_utc(schedule.next_run_dt)
        if schedule_end_utc < now and next_run_utc > schedule_end_utc:
            schedule.enabled = False
            run = await _create_skipped_run(
                db,
                schedule,
                message="Schedule ended on its configured end date.",
                summary={"schedule_end_dt": _iso_utc(schedule.schedule_end_dt)},
            )
            return None, run

    if due_only and schedule.end_condition == END_CONDITION_END_AFTER_RUNS and schedule.end_after_runs is not None:
        completed_runs = await _completed_schedule_run_count(db, schedule.schedule_id)
        if completed_runs >= schedule.end_after_runs:
            schedule.enabled = False
            run = await _create_skipped_run(
                db,
                schedule,
                message="Schedule reached its configured run limit.",
                summary={"completed_run_count": completed_runs, "end_after_runs": schedule.end_after_runs},
            )
            return None, run

    active_result = await db.execute(
        select(AuditReviewScheduleRun)
        .where(
            AuditReviewScheduleRun.schedule_id == schedule.schedule_id,
            AuditReviewScheduleRun.status == AUDIT_REVIEW_SCHEDULE_RUN_STATUS_STARTED,
            AuditReviewScheduleRun.completed_at.is_(None),
        )
        .order_by(AuditReviewScheduleRun.started_at.desc())
        .limit(1)
    )
    active_run = active_result.scalars().first()
    if active_run is not None:
        if _to_utc(active_run.started_at) >= now - STARTED_RUN_STALE_AFTER:
            run = await _create_skipped_run(
                db,
                schedule,
                message="Another scheduler run is already in progress for this schedule.",
                summary={"active_run_id": str(active_run.run_id), "active_started_at": _iso_utc(active_run.started_at)},
            )
            return None, run

        active_run.status = AUDIT_REVIEW_SCHEDULE_RUN_STATUS_FAILED
        active_run.completed_at = now
        active_run.error_message = "Scheduler run was marked failed because it was stale."
        active_run.message = "Stale STARTED scheduler run was closed before retry."
        active_summary = dict(active_run.run_summary_json or {})
        active_summary["stale_closed_at"] = _iso_utc(now)
        active_run.run_summary_json = active_summary

    configured_retrieval_mode = _schedule_audit_retrieval_mode(schedule)
    frequency_value = str(getattr(schedule, "frequency", "") or "").strip().upper()
    range_reference_dt = (
        schedule.next_run_dt
        if configured_retrieval_mode == AUDIT_RETRIEVAL_MODE_AUTO and (due_only or frequency_value in {"DAILY", "MONTHLY"})
        else now
    )
    review_start_dt, review_end_dt, audit_retrieval_mode = await _audit_retrieval_range(
        db,
        schedule,
        range_reference_dt,
        use_last_successful_anchor=not (
            trigger_mode == "SCHEDULED_MANUAL"
            and schedule.frequency == "DAILY"
            and configured_retrieval_mode == AUDIT_RETRIEVAL_MODE_SINCE_LAST_SUCCESSFUL
        ),
    )

    selected_types = _schedule_selected_types(schedule)
    candidate_key = build_audit_review_candidate_key(
        schedule.asset_id,
        "|".join(selected_types),
        review_start_dt,
        review_end_dt,
    )
    duplicate_result = await db.execute(
        select(AuditReviewJob)
        .where(
            AuditReviewJob.asset_id == schedule.asset_id,
            AuditReviewJob.review_candidate_key == candidate_key,
            AuditReviewJob.status != AUDIT_REVIEW_STATUS_FAILED,
        )
        .order_by(AuditReviewJob.created_dt.desc(), AuditReviewJob.job_id.desc())
        .limit(1)
    )
    duplicate_job = duplicate_result.scalars().first()
    if duplicate_job is not None:
        run = await _create_skipped_run(
            db,
            schedule,
            message="Matching audit review job already exists for this schedule period.",
            job_id=duplicate_job.job_id,
            advance_next_run=due_only,
            summary={
                "review_start_dt": _iso_utc(review_start_dt),
                "review_end_dt": _iso_utc(review_end_dt),
                "duplicate_job_id": str(duplicate_job.job_id),
            },
        )
        return None, run

    run = AuditReviewScheduleRun(
        schedule_id=schedule.schedule_id,
        asset_id=schedule.asset_id,
        job_id=None,
        status=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_STARTED,
        started_at=now,
        completed_at=None,
        message="Scheduled audit review workflow started.",
        error_message=None,
        run_summary_json={
            "schedule": _schedule_summary(schedule),
            "trigger_mode": trigger_mode,
            "audit_retrieval_mode": audit_retrieval_mode,
            "review_start_dt": _iso_utc(review_start_dt),
            "review_end_dt": _iso_utc(review_end_dt),
            "candidate_key": candidate_key,
        },
    )
    db.add(run)
    if due_only and _to_utc(schedule.next_run_dt) <= now:
        schedule.next_run_dt = calculate_next_run_dt(schedule, now)
        schedule.modified_dt = now
        run_summary = dict(run.run_summary_json or {})
        run_summary["reserved_next_run_dt"] = _iso_utc(schedule.next_run_dt)
        run.run_summary_json = run_summary
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        schedule = await _require_schedule(db, schedule_id)
        skipped_run = await _create_skipped_run(
            db,
            schedule,
            message="Another scheduler run started first for this schedule.",
            summary={"integrity_error": _safe_error_message(exc)},
        )
        return None, skipped_run

    return (
        ScheduleExecution(
            run_id=run.run_id,
            schedule_id=schedule.schedule_id,
            asset_id=schedule.asset_id,
            audit_trail_type=schedule.audit_trail_type,
            review_scope=schedule.review_scope,
            selected_audit_trail_types=selected_types,
            vault_dns=schedule.vault_dns,
            veeva_instance_name=schedule.veeva_instance_name,
            veeva_app_name=schedule.veeva_app_name,
            frequency=schedule.frequency,
            audit_retrieval_mode=audit_retrieval_mode,
            timezone_name=schedule.timezone,
            business_start_hour=_business_start_hour(schedule),
            business_end_hour=_business_end_hour(schedule),
            review_start_dt=review_start_dt,
            review_end_dt=review_end_dt,
            started_at=now,
            requested_by=DEFAULT_SCHEDULER_ACTOR,
            trigger_mode=trigger_mode,
        ),
        run,
    )


async def _set_run_job(db: AsyncSession, execution: ScheduleExecution, job_id: uuid.UUID) -> None:
    run = await _require_run(db, execution.run_id)
    run.job_id = job_id
    summary = dict(run.run_summary_json or {})
    summary["job_id"] = str(job_id)
    summary["job_created_at"] = _iso_utc(_utc_now())
    run.run_summary_json = summary
    await db.commit()


async def _mark_job_failed_safe(db: AsyncSession, job_id: uuid.UUID, message: str) -> None:
    result = await db.execute(select(AuditReviewJob).where(AuditReviewJob.job_id == job_id))
    job = result.scalars().first()
    if job is None:
        return
    now = _utc_now()
    job.status = AUDIT_REVIEW_STATUS_FAILED
    job.error_message = _safe_error_message(message)
    job.completed_at = now
    job.modified_dt = now
    await db.commit()


async def _finish_schedule_run(
    db: AsyncSession,
    execution: ScheduleExecution,
    *,
    status_value: str,
    message: str,
    error_message: str | None = None,
    job_id: uuid.UUID | None = None,
    report: AuditReviewReportGenerateResponse | None = None,
    extract_summary: dict[str, Any] | None = None,
    analysis_summary: dict[str, Any] | None = None,
    notification_summary: dict[str, Any] | None = None,
) -> AuditReviewScheduleRun:
    completed_at = _utc_now()
    run = await _require_run(db, execution.run_id)
    summary = dict(run.run_summary_json or {})
    summary.update(
        {
            "completed_at": _iso_utc(completed_at),
            "status": status_value,
            "review_start_dt": _iso_utc(execution.review_start_dt),
            "review_end_dt": _iso_utc(execution.review_end_dt),
            "audit_retrieval_mode": execution.audit_retrieval_mode,
            "review_scope": execution.review_scope,
            "selected_audit_trail_types": execution.selected_audit_trail_types,
            "business_timezone": execution.timezone_name,
            "business_start_hour": execution.business_start_hour,
            "business_end_hour": execution.business_end_hour,
            "result_summary": message,
        }
    )
    if extract_summary is not None:
        summary["extraction"] = extract_summary
    if analysis_summary is not None:
        summary["analysis"] = analysis_summary
    if report is not None:
        summary["report"] = {
            "report_id": str(report.report_id),
            "status": report.status,
            "overall_score": report.overall_score,
            "rating": report.rating,
        }
    if notification_summary is not None:
        summary["notification"] = notification_summary

    run.status = status_value
    run.completed_at = completed_at
    run.message = message
    run.error_message = _safe_error_message(error_message) if error_message else None
    run.job_id = job_id or run.job_id
    run.run_summary_json = summary

    schedule = await _require_schedule(db, execution.schedule_id)
    schedule.last_run_dt = completed_at
    if job_id is not None:
        schedule.last_job_id = job_id
    if _to_utc(schedule.next_run_dt) <= _to_utc(execution.started_at):
        schedule.next_run_dt = calculate_next_run_dt(schedule, completed_at)
    if (
        status_value == AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED
        and execution.trigger_mode == "SCHEDULED_DUE"
        and schedule.schedule_end_dt is not None
        and schedule.end_condition == END_CONDITION_END_ON_DATE
        and _to_utc(schedule.next_run_dt) > _to_utc(schedule.schedule_end_dt)
    ):
        schedule.enabled = False
        summary["schedule_completed"] = True
        summary["schedule_end_dt"] = _iso_utc(schedule.schedule_end_dt)
    if status_value == AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED and execution.audit_retrieval_mode == AUDIT_RETRIEVAL_MODE_CUSTOM:
        if execution.frequency == "DAILY":
            schedule.audit_retrieval_mode = AUDIT_RETRIEVAL_MODE_AUTO
            schedule.custom_audit_start_dt = None
            schedule.custom_audit_end_dt = None
            summary["next_audit_retrieval_mode"] = AUDIT_RETRIEVAL_MODE_AUTO
        else:
            schedule.audit_retrieval_mode = AUDIT_RETRIEVAL_MODE_CUSTOM
        if execution.frequency != "DAILY" and execution.trigger_mode == "SCHEDULED_DUE":
            next_custom_start, next_custom_end = _next_custom_audit_range_after_run(
                schedule,
                execution.review_start_dt,
                execution.review_end_dt,
            )
            schedule.custom_audit_start_dt = next_custom_start
            schedule.custom_audit_end_dt = next_custom_end
            summary["next_custom_audit_start_dt"] = _iso_utc(next_custom_start)
            summary["next_custom_audit_end_dt"] = _iso_utc(next_custom_end)
        elif execution.frequency != "DAILY":
            schedule.custom_audit_start_dt = execution.review_start_dt
            schedule.custom_audit_end_dt = execution.review_end_dt
    summary["next_run_dt"] = _iso_utc(schedule.next_run_dt)
    run.run_summary_json = summary
    schedule.modified_dt = completed_at

    await db.commit()
    return run


def _scheduler_actor(execution: ScheduleExecution) -> str:
    actor = str(execution.requested_by or "").strip()
    return actor or DEFAULT_SCHEDULER_ACTOR


def _current_user_actor_label(current_user: CurrentUser | None) -> str | None:
    if current_user is None:
        return None
    full_name = str(current_user.full_name or "").strip()
    email = str(current_user.email or "").strip()
    return full_name or email or None


async def _generate_scheduled_draft_report(
    db: AsyncSession,
    job_id: uuid.UUID,
    execution: ScheduleExecution,
) -> tuple[AuditReviewReportGenerateResponse, dict[str, Any]]:
    generated_report = await generate_audit_review_report(db, job_id)
    notifications = await prepare_audit_review_notifications(
        db,
        generated_report.report_id,
        PrepareNotificationsRequest(
            requested_by=_scheduler_actor(execution),
            regenerate=False,
        ),
    )
    return generated_report, {
        "status": "READY",
        "message": SCHEDULED_DRAFT_READY_MESSAGE,
        "count": len(notifications),
        "notification_ids": [str(notification.notification_id) for notification in notifications],
    }


async def _latest_report_for_job(
    db: AsyncSession,
    job_id: uuid.UUID,
) -> AuditReviewReportGenerateResponse | None:
    result = await db.execute(
        select(AuditReviewReport)
        .where(AuditReviewReport.job_id == job_id)
        .order_by(AuditReviewReport.created_dt.desc(), AuditReviewReport.report_id.desc())
        .limit(1)
    )
    report = result.scalars().first()
    if report is None:
        return None

    summary = report.report_summary_json or {}
    workflow_metadata = build_report_workflow_metadata(report)
    return AuditReviewReportGenerateResponse(
        report_id=report.report_id,
        job_id=report.job_id,
        asset_id=report.asset_id,
        status=report.report_status,
        overall_score=int(summary.get("overall_score") or 0),
        rating=str(summary.get("rating") or "CRITICAL_RISK"),
        report_summary=summary,
        review_type=report.review_type or workflow_metadata.get("review_type"),
        trigger_source=report.trigger_source or workflow_metadata.get("trigger_source"),
        schedule_id=report.schedule_id,
        schedule_run_id=report.schedule_run_id,
        workflow_metadata_json=report.workflow_metadata_json,
        workflow_metadata=workflow_metadata,
        submitted_by=report.submitted_by,
        submitted_dt=report.submitted_dt,
        reviewed_by=report.reviewed_by,
        reviewed_dt=report.reviewed_dt,
        reviewer_comments=report.reviewer_comments,
        approval_decision_json=report.approval_decision_json,
        is_e_signed=bool(report.is_e_signed),
        e_signed_at=report.e_signed_at,
        e_signed_by_user_id=report.e_signed_by_user_id,
        is_locked=bool(report.is_locked),
        locked_at=report.locked_at,
        locked_by_user_id=report.locked_by_user_id,
        final_pdf_path=report.final_pdf_path,
        final_pdf_hash=report.final_pdf_hash,
        report_version=report.report_version or workflow_metadata.get("report_version"),
    )


async def _response_for_run(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    run: AuditReviewScheduleRun,
    *,
    job_detail: AuditReviewJobDetailResponse | None = None,
    report: AuditReviewReportGenerateResponse | None = None,
) -> AuditReviewScheduleRunNowResponse:
    schedule = await _require_schedule(db, schedule_id)
    if job_detail is None and run.job_id is not None:
        try:
            job_detail = await get_audit_review_job(db, run.job_id)
        except AuditReviewServiceError:
            job_detail = None
    if report is None and run.job_id is not None:
        report = await _latest_report_for_job(db, run.job_id)
    return AuditReviewScheduleRunNowResponse(
        schedule=_build_schedule_response(schedule),
        run=_build_run_response(run),
        job=job_detail,
        report=report,
    )


async def run_audit_review_schedule_now(
    db: AsyncSession,
    schedule_id: uuid.UUID,
) -> AuditReviewScheduleRunNowResponse:
    execution, run = await _start_schedule_execution(
        db,
        schedule_id,
        trigger_mode="SCHEDULED_MANUAL",
        due_only=False,
    )
    if execution is None:
        if run is None:
            raise AuditReviewValidationError("Audit review schedule run was not started.")
        return await _response_for_run(db, schedule_id, run)

    job_id: uuid.UUID | None = None
    report: AuditReviewReportGenerateResponse | None = None
    extract_summary: dict[str, Any] | None = None
    analysis_summary: dict[str, Any] | None = None
    notification_summary: dict[str, Any] | None = None
    try:
        create_payload = AuditReviewJobCreateRequest(
            review_start_dt=execution.review_start_dt,
            review_end_dt=execution.review_end_dt,
            audit_trail_type=execution.audit_trail_type,
            review_scope=execution.review_scope,
            selected_audit_trail_types=execution.selected_audit_trail_types,
            veeva_instance_name=execution.veeva_instance_name,
            veeva_app_name=execution.veeva_app_name,
            vault_dns=execution.vault_dns,
            requested_by=execution.requested_by,
        )
        created = await create_audit_review_job(
            db,
            execution.asset_id,
            create_payload,
            period_basis="SCHEDULED",
            trigger_mode=execution.trigger_mode,
            input_snapshot_extra={
                "schedule_id": str(execution.schedule_id),
                "schedule_run_id": str(execution.run_id),
                "scheduler_trigger_mode": execution.trigger_mode,
                "audit_retrieval_mode": execution.audit_retrieval_mode,
            },
        )
        job_id = created.job_id
        await _set_run_job(db, execution, job_id)

        extracted = await extract_audit_review_job(db, job_id)
        extract_summary = extracted.extraction_summary_json
        analyzed = await analyze_audit_review_job(
            db,
            job_id,
            AuditReviewAnalyzeRequest(
                business_timezone=execution.timezone_name,
                business_start_hour=execution.business_start_hour,
                business_end_hour=execution.business_end_hour,
            ),
        )
        analysis_summary = {
            "overall_score": analyzed.overall_score,
            "rating": analyzed.rating,
            "score_label": analyzed.score_label,
            "total_records_analyzed": analyzed.total_records_analyzed,
            "total_findings": analyzed.total_findings,
            "finding_counts_by_severity": analyzed.finding_counts_by_severity,
            "score_breakdown": analyzed.score_breakdown,
            "audit_type_scores": analyzed.audit_type_scores,
            "checkpoint_scores": analyzed.checkpoint_scores,
            "checklist_applicability": analyzed.checklist_applicability,
        }
        report, notification_summary = await _generate_scheduled_draft_report(db, job_id, execution)
        run = await _finish_schedule_run(
            db,
            execution,
            status_value=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED,
            message=SCHEDULED_DRAFT_READY_MESSAGE,
            job_id=job_id,
            report=report,
            extract_summary=extract_summary,
            analysis_summary=analysis_summary,
            notification_summary=notification_summary,
        )
        job_detail = await get_audit_review_job(db, job_id)
        return await _response_for_run(db, schedule_id, run, job_detail=job_detail, report=report)
    except AuditReviewServiceError as exc:
        if job_id is not None:
            await _mark_job_failed_safe(db, job_id, exc.message)
        run = await _finish_schedule_run(
            db,
            execution,
            status_value=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_FAILED,
            message="Scheduled audit review failed.",
            error_message=exc.message,
            job_id=job_id,
            extract_summary=extract_summary,
            analysis_summary=analysis_summary,
        )
        return await _response_for_run(db, schedule_id, run)
    except Exception as exc:  # noqa: BLE001 - scheduler run logs must capture unexpected failures safely.
        message = _safe_error_message(exc)
        if job_id is not None:
            await _mark_job_failed_safe(db, job_id, message)
        run = await _finish_schedule_run(
            db,
            execution,
            status_value=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_FAILED,
            message="Scheduled audit review failed.",
            error_message=message,
            job_id=job_id,
            extract_summary=extract_summary,
            analysis_summary=analysis_summary,
        )
        return await _response_for_run(db, schedule_id, run)


async def run_due_audit_review_schedules(db: AsyncSession) -> AuditReviewSchedulerRunDueResponse:
    now = _utc_now()
    result = await db.execute(
        select(AuditReviewSchedule.schedule_id)
        .where(
            AuditReviewSchedule.enabled.is_(True),
            AuditReviewSchedule.next_run_dt <= now,
        )
        .order_by(AuditReviewSchedule.next_run_dt.asc(), AuditReviewSchedule.created_dt.asc())
    )
    schedule_ids = list(result.scalars().all())

    runs: list[AuditReviewScheduleRunResponse] = []
    for schedule_id in schedule_ids:
        try:
            response = await run_audit_review_schedule_due(db, schedule_id)
            runs.append(response.run)
        except Exception:  # noqa: BLE001 - one broken schedule must not block the due batch.
            await db.rollback()
            continue

    completed_count = sum(1 for run in runs if run.status == AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED)
    failed_count = sum(1 for run in runs if run.status == AUDIT_REVIEW_SCHEDULE_RUN_STATUS_FAILED)
    skipped_count = sum(1 for run in runs if run.status == AUDIT_REVIEW_SCHEDULE_RUN_STATUS_SKIPPED)
    return AuditReviewSchedulerRunDueResponse(
        processed_count=len(runs),
        completed_count=completed_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        runs=runs,
    )


async def process_due_audit_review_schedules_background(
    *,
    poll_interval_seconds: int = 60,
    initial_delay_seconds: int = 10,
) -> None:
    interval = poll_interval_seconds if poll_interval_seconds > 0 else 60
    initial_delay = max(0, initial_delay_seconds)
    if initial_delay:
        await asyncio.sleep(initial_delay)

    while True:
        try:
            async with SessionLocal() as db:
                result = await run_due_audit_review_schedules(db)
            if result.processed_count:
                logger.info(
                    "audit_review_scheduler_due_run processed=%s completed=%s failed=%s skipped=%s",
                    result.processed_count,
                    result.completed_count,
                    result.failed_count,
                    result.skipped_count,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("audit_review_scheduler_due_run_failed")

        await asyncio.sleep(interval)


async def run_audit_review_schedule_due(
    db: AsyncSession,
    schedule_id: uuid.UUID,
) -> AuditReviewScheduleRunNowResponse:
    execution, run = await _start_schedule_execution(
        db,
        schedule_id,
        trigger_mode="SCHEDULED_DUE",
        due_only=True,
    )
    if execution is None:
        if run is None:
            raise AuditReviewValidationError("Audit review schedule run was not started.")
        return await _response_for_run(db, schedule_id, run)

    return await run_audit_review_schedule_execution(db, execution, schedule_id)


async def run_audit_review_schedule_execution(
    db: AsyncSession,
    execution: ScheduleExecution,
    schedule_id: uuid.UUID,
) -> AuditReviewScheduleRunNowResponse:
    job_id: uuid.UUID | None = None
    report: AuditReviewReportGenerateResponse | None = None
    extract_summary: dict[str, Any] | None = None
    analysis_summary: dict[str, Any] | None = None
    notification_summary: dict[str, Any] | None = None
    try:
        create_payload = AuditReviewJobCreateRequest(
            review_start_dt=execution.review_start_dt,
            review_end_dt=execution.review_end_dt,
            audit_trail_type=execution.audit_trail_type,
            review_scope=execution.review_scope,
            selected_audit_trail_types=execution.selected_audit_trail_types,
            veeva_instance_name=execution.veeva_instance_name,
            veeva_app_name=execution.veeva_app_name,
            vault_dns=execution.vault_dns,
            requested_by=execution.requested_by,
        )
        created = await create_audit_review_job(
            db,
            execution.asset_id,
            create_payload,
            period_basis="SCHEDULED",
            trigger_mode=execution.trigger_mode,
            input_snapshot_extra={
                "schedule_id": str(execution.schedule_id),
                "schedule_run_id": str(execution.run_id),
                "scheduler_trigger_mode": execution.trigger_mode,
                "audit_retrieval_mode": execution.audit_retrieval_mode,
            },
        )
        job_id = created.job_id
        await _set_run_job(db, execution, job_id)

        extracted = await extract_audit_review_job(db, job_id)
        extract_summary = extracted.extraction_summary_json
        analyzed = await analyze_audit_review_job(
            db,
            job_id,
            AuditReviewAnalyzeRequest(
                business_timezone=execution.timezone_name,
                business_start_hour=execution.business_start_hour,
                business_end_hour=execution.business_end_hour,
            ),
        )
        analysis_summary = {
            "overall_score": analyzed.overall_score,
            "rating": analyzed.rating,
            "score_label": analyzed.score_label,
            "total_records_analyzed": analyzed.total_records_analyzed,
            "total_findings": analyzed.total_findings,
            "finding_counts_by_severity": analyzed.finding_counts_by_severity,
            "score_breakdown": analyzed.score_breakdown,
            "audit_type_scores": analyzed.audit_type_scores,
            "checkpoint_scores": analyzed.checkpoint_scores,
            "checklist_applicability": analyzed.checklist_applicability,
        }
        report, notification_summary = await _generate_scheduled_draft_report(db, job_id, execution)
        run = await _finish_schedule_run(
            db,
            execution,
            status_value=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED,
            message=SCHEDULED_DRAFT_READY_MESSAGE,
            job_id=job_id,
            report=report,
            extract_summary=extract_summary,
            analysis_summary=analysis_summary,
            notification_summary=notification_summary,
        )
        job_detail = await get_audit_review_job(db, job_id)
        return await _response_for_run(db, schedule_id, run, job_detail=job_detail, report=report)
    except AuditReviewServiceError as exc:
        if job_id is not None:
            await _mark_job_failed_safe(db, job_id, exc.message)
        run = await _finish_schedule_run(
            db,
            execution,
            status_value=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_FAILED,
            message="Scheduled audit review failed.",
            error_message=exc.message,
            job_id=job_id,
            extract_summary=extract_summary,
            analysis_summary=analysis_summary,
        )
        return await _response_for_run(db, schedule_id, run)
    except Exception as exc:  # noqa: BLE001
        message = _safe_error_message(exc)
        if job_id is not None:
            await _mark_job_failed_safe(db, job_id, message)
        run = await _finish_schedule_run(
            db,
            execution,
            status_value=AUDIT_REVIEW_SCHEDULE_RUN_STATUS_FAILED,
            message="Scheduled audit review failed.",
            error_message=message,
            job_id=job_id,
            extract_summary=extract_summary,
            analysis_summary=analysis_summary,
        )
        return await _response_for_run(db, schedule_id, run)


async def list_audit_review_schedule_runs(
    db: AsyncSession,
    schedule_id: uuid.UUID,
) -> list[AuditReviewScheduleRunResponse]:
    await _require_schedule(db, schedule_id)
    result = await db.execute(
        select(AuditReviewScheduleRun)
        .where(AuditReviewScheduleRun.schedule_id == schedule_id)
        .order_by(AuditReviewScheduleRun.started_at.desc(), AuditReviewScheduleRun.run_id.desc())
    )
    return [_build_run_response(run) for run in result.scalars().all()]
