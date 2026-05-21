import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.audit_review_job import AuditReviewJob
from app.models.audit_review_notification import AuditReviewNotification
from app.models.audit_review_report import AuditReviewReport
from app.schemas.audit_review_schema import (
    AUDIT_REVIEW_NOTIFICATION_CHANNEL_BOTH,
    AUDIT_REVIEW_NOTIFICATION_CHANNEL_EMAIL,
    AUDIT_REVIEW_NOTIFICATION_CHANNEL_IN_APP,
    AUDIT_REVIEW_NOTIFICATION_PRIORITIES,
    AUDIT_REVIEW_NOTIFICATION_STATUS_DISMISSED,
    AUDIT_REVIEW_NOTIFICATION_STATUS_FAILED,
    AUDIT_REVIEW_NOTIFICATION_STATUS_PENDING,
    AUDIT_REVIEW_NOTIFICATION_STATUS_READY,
    AUDIT_REVIEW_NOTIFICATION_STATUS_SENT,
    AUDIT_REVIEW_NOTIFICATION_STATUSES,
    AUDIT_REVIEW_REPORT_STATUS_APPROVED,
    AuditReviewNotificationResponse,
    DismissNotificationRequest,
    PrepareNotificationsRequest,
    SendNotificationRequest,
    SendNotificationResponse,
    SendNotificationsResponse,
)
from app.services.audit_review_service import AuditReviewNotFoundError, AuditReviewValidationError


@dataclass(frozen=True)
class EscalationRule:
    notification_type: str
    priority: str
    required_action: str
    recipient_roles: tuple[str, ...]


ESCALATION_MATRIX: dict[str, EscalationRule] = {
    "COMPLIANT": EscalationRule(
        notification_type="AUDIT_REVIEW_COMPLIANT",
        priority="LOW",
        required_action="Document and close. Schedule next review.",
        recipient_roles=("System Owner",),
    ),
    "MINOR_FINDINGS": EscalationRule(
        notification_type="AUDIT_REVIEW_MINOR_FINDINGS",
        priority="MEDIUM",
        required_action="Observation report; CAPA within 30 days.",
        recipient_roles=("QA Manager", "IT Compliance"),
    ),
    "MAJOR_FINDINGS": EscalationRule(
        notification_type="AUDIT_REVIEW_MAJOR_FINDINGS",
        priority="HIGH",
        required_action="Formal CAPA + Deviation; escalate in 7 days.",
        recipient_roles=("QA Director", "Regulatory Affairs"),
    ),
    "CRITICAL_RISK": EscalationRule(
        notification_type="AUDIT_REVIEW_CRITICAL_RISK",
        priority="CRITICAL",
        required_action="Immediate escalation; system suspension review.",
        recipient_roles=("VP Quality", "Executive Leadership", "Regulatory Authority"),
    ),
}

EMAIL_NOT_CONFIGURED_MESSAGE = "Email delivery is not configured. Notification is available in-app."
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_datetime(value: datetime | None) -> str | None:
    converted = _to_utc(value)
    if converted is None:
        return None
    return converted.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _safe_int(value: Any, fallback: int = 0) -> int:
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_status(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    if cleaned not in AUDIT_REVIEW_NOTIFICATION_STATUSES:
        raise AuditReviewValidationError(
            "Unsupported notification status filter.",
            data={"status": value, "allowed_statuses": sorted(AUDIT_REVIEW_NOTIFICATION_STATUSES)},
        )
    return cleaned


def _normalize_priority(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    if cleaned not in AUDIT_REVIEW_NOTIFICATION_PRIORITIES:
        raise AuditReviewValidationError(
            "Unsupported notification priority filter.",
            data={"priority": value, "allowed_priorities": sorted(AUDIT_REVIEW_NOTIFICATION_PRIORITIES)},
        )
    return cleaned


def _is_email(value: str | None) -> bool:
    return bool(value and EMAIL_PATTERN.match(value.strip()))


async def _require_asset(db: AsyncSession, asset_id: uuid.UUID) -> Asset:
    result = await db.execute(select(Asset).where(Asset.asset_uuid == asset_id))
    asset = result.scalars().first()
    if asset is None:
        raise AuditReviewNotFoundError("Asset not found")
    return asset


async def _require_report(db: AsyncSession, report_id: uuid.UUID) -> AuditReviewReport:
    result = await db.execute(
        select(AuditReviewReport)
        .options(
            selectinload(AuditReviewReport.job),
            selectinload(AuditReviewReport.asset),
        )
        .where(AuditReviewReport.report_id == report_id)
    )
    report = result.scalars().first()
    if report is None:
        raise AuditReviewNotFoundError("Audit review report not found")
    return report


async def _require_notification(db: AsyncSession, notification_id: uuid.UUID) -> AuditReviewNotification:
    result = await db.execute(
        select(AuditReviewNotification).where(AuditReviewNotification.notification_id == notification_id)
    )
    notification = result.scalars().first()
    if notification is None:
        raise AuditReviewNotFoundError("Audit review notification not found")
    return notification


def _notification_query() -> Select[tuple[AuditReviewNotification]]:
    return select(AuditReviewNotification).order_by(
        func.coalesce(AuditReviewNotification.sent_dt, AuditReviewNotification.created_dt).desc(),
        AuditReviewNotification.created_dt.desc(),
        AuditReviewNotification.notification_id.desc(),
    )


def _metric_value(*values: Any, fallback: int = 0) -> int:
    for value in values:
        if value is not None:
            return _safe_int(value, fallback)
    return fallback


def _finding_count(summary: dict[str, Any], key: str) -> int:
    return _metric_value(
        summary.get(key),
        summary.get(key.upper()),
        summary.get(f"{key}_findings"),
        summary.get(f"{key.upper()}_findings"),
        fallback=0,
    )


def _extract_report_metrics(report: AuditReviewReport) -> dict[str, Any]:
    report_summary = _as_dict(report.report_summary_json)
    report_json = _as_dict(report.report_payload_json)
    execution_summary = _as_dict(report_json.get("execution_summary"))
    review_scope = _as_dict(report_json.get("review_scope"))
    finding_summary = _as_dict(report_json.get("finding_summary") or report_summary.get("finding_summary"))
    job = report.job
    analysis_summary = _as_dict(job.analysis_summary_json if job is not None else None)
    analysis_counts = _as_dict(analysis_summary.get("finding_counts_by_severity"))

    rating = _safe_str(
        report_summary.get("rating")
        or execution_summary.get("rating")
        or report_json.get("rating")
        or analysis_summary.get("rating"),
        "",
    ).upper()
    overall_score = _metric_value(
        report_summary.get("overall_score"),
        execution_summary.get("overall_score"),
        report_json.get("overall_score"),
        analysis_summary.get("overall_score"),
        fallback=0,
    )
    total_findings = _metric_value(
        report_summary.get("total_findings"),
        execution_summary.get("total_findings"),
        analysis_summary.get("total_findings"),
        fallback=0,
    )

    critical_count = _finding_count(finding_summary, "critical") or _finding_count(analysis_counts, "critical")
    high_count = _finding_count(finding_summary, "high") or _finding_count(analysis_counts, "high")
    medium_count = _finding_count(finding_summary, "medium") or _finding_count(analysis_counts, "medium")
    low_count = _finding_count(finding_summary, "low") or _finding_count(analysis_counts, "low")

    return {
        "rating": rating,
        "overall_score": overall_score,
        "total_findings": total_findings,
        "critical_findings": critical_count,
        "high_findings": high_count,
        "medium_findings": medium_count,
        "low_findings": low_count,
        "review_start_dt": review_scope.get("review_start_dt") or _iso_datetime(job.review_start_dt if job else None),
        "review_end_dt": review_scope.get("review_end_dt") or _iso_datetime(job.review_end_dt if job else None),
        "audit_trail_type": review_scope.get("audit_trail_type") or _safe_str(job.audit_trail_type if job else None, "N/A"),
        "veeva_instance_name": review_scope.get("veeva_instance_name")
        or _safe_str(job.veeva_instance_name if job else None, "N/A"),
        "veeva_app_name": review_scope.get("veeva_app_name") or _safe_str(job.veeva_app_name if job else None, "N/A"),
    }


def _asset_name(asset: Asset | None, asset_id: uuid.UUID) -> str:
    return _safe_str(asset.asset_name if asset else None, str(asset_id))


def _asset_code(asset: Asset | None, asset_id: uuid.UUID) -> str:
    return _safe_str(asset.asset_id if asset else None, str(asset_id))


def _recipient_email_for_role(role: str, asset: Asset | None) -> str | None:
    if role == "System Owner" and asset is not None and _is_email(asset.asset_owner):
        return asset.asset_owner.strip()
    return None


def _build_subject(priority: str, rating: str, asset: Asset | None, asset_id: uuid.UUID) -> str:
    asset_label = _asset_name(asset, asset_id) or _asset_code(asset, asset_id)
    return f"[{priority}] Veeva Audit Trail Review - {rating} - {asset_label}"[:300]


def _build_message(
    *,
    report: AuditReviewReport,
    asset: Asset | None,
    metrics: dict[str, Any],
    rule: EscalationRule,
    recipient_role: str,
    is_draft_notification: bool,
) -> str:
    review_period = f"{_safe_str(metrics.get('review_start_dt'), 'N/A')} to {_safe_str(metrics.get('review_end_dt'), 'N/A')}"
    draft_note = (
        "\nDraft notification note: This report is not APPROVED. Notifications are draft/preliminary."
        if is_draft_notification
        else ""
    )
    reviewer_comments = _safe_str(report.reviewer_comments, "N/A")
    return "\n".join(
        [
            "Veeva audit trail periodic review notification",
            "",
            f"Recipient role: {recipient_role}",
            f"Asset name: {_asset_name(asset, report.asset_id)}",
            f"Asset ID/code: {_asset_code(asset, report.asset_id)}",
            f"Veeva instance: {_safe_str(metrics.get('veeva_instance_name'), 'N/A')}",
            f"Veeva app: {_safe_str(metrics.get('veeva_app_name'), 'N/A')}",
            f"Audit trail type: {_safe_str(metrics.get('audit_trail_type'), 'N/A')}",
            f"Review period: {review_period}",
            f"Overall score: {metrics['overall_score']}",
            f"Rating: {metrics['rating']}",
            f"Total findings: {metrics['total_findings']}",
            f"Critical findings: {metrics['critical_findings']}",
            f"High findings: {metrics['high_findings']}",
            f"Medium findings: {metrics['medium_findings']}",
            f"Low findings: {metrics['low_findings']}",
            f"Required action: {rule.required_action}",
            f"Report ID: {report.report_id}",
            f"Job ID: {report.job_id}",
            f"Report status: {report.report_status}",
            f"Reviewer comments: {reviewer_comments}",
            draft_note,
        ]
    ).strip()


def _build_metadata(
    *,
    report: AuditReviewReport,
    asset: Asset | None,
    metrics: dict[str, Any],
    rule: EscalationRule,
    requested_by: str | None,
    is_draft_notification: bool,
    prepared_at: datetime,
) -> dict[str, Any]:
    return {
        "required_action": rule.required_action,
        "stakeholder_roles": list(rule.recipient_roles),
        "is_draft_notification": is_draft_notification,
        "report_status": report.report_status,
        "prepared_by": requested_by,
        "prepared_dt": _iso_datetime(prepared_at),
        "email_configured": False,
        "asset_name": _asset_name(asset, report.asset_id),
        "asset_code": _asset_code(asset, report.asset_id),
        "review_period": {
            "start": metrics.get("review_start_dt"),
            "end": metrics.get("review_end_dt"),
        },
    }


def _build_response(notification: AuditReviewNotification) -> AuditReviewNotificationResponse:
    return AuditReviewNotificationResponse(
        notification_id=notification.notification_id,
        report_id=notification.report_id,
        job_id=notification.job_id,
        asset_id=notification.asset_id,
        notification_type=notification.notification_type,
        priority=notification.priority,
        rating=notification.rating,
        recipient_role=notification.recipient_role,
        recipient_email=notification.recipient_email,
        subject=notification.subject,
        message=notification.message,
        status=notification.status,
        delivery_channel=notification.delivery_channel,
        created_by=notification.created_by,
        created_dt=notification.created_dt,
        sent_dt=notification.sent_dt,
        error_message=notification.error_message,
        metadata_json=notification.metadata_json or {},
    )


async def _list_report_notifications_for_type(
    db: AsyncSession,
    report_id: uuid.UUID,
    notification_type: str,
) -> list[AuditReviewNotification]:
    result = await db.execute(
        _notification_query().where(
            AuditReviewNotification.report_id == report_id,
            AuditReviewNotification.notification_type == notification_type,
            AuditReviewNotification.status != AUDIT_REVIEW_NOTIFICATION_STATUS_DISMISSED,
        )
    )
    return list(result.scalars().all())


async def prepare_audit_review_notifications(
    db: AsyncSession,
    report_id: uuid.UUID,
    payload: PrepareNotificationsRequest,
) -> list[AuditReviewNotificationResponse]:
    report = await _require_report(db, report_id)
    metrics = _extract_report_metrics(report)
    rating = metrics["rating"]
    rule = ESCALATION_MATRIX.get(rating)
    if rule is None:
        raise AuditReviewValidationError(
            "Audit review report rating is missing or unsupported for notification escalation.",
            data={"report_id": str(report.report_id), "rating": rating, "supported_ratings": sorted(ESCALATION_MATRIX)},
        )

    prepared_at = _utc_now()
    asset = report.asset
    is_draft_notification = report.report_status != AUDIT_REVIEW_REPORT_STATUS_APPROVED

    if payload.regenerate:
        existing_ready_result = await db.execute(
            select(AuditReviewNotification).where(
                AuditReviewNotification.report_id == report.report_id,
                AuditReviewNotification.notification_type == rule.notification_type,
                AuditReviewNotification.status.in_(
                    [AUDIT_REVIEW_NOTIFICATION_STATUS_PENDING, AUDIT_REVIEW_NOTIFICATION_STATUS_READY]
                ),
            )
        )
        for existing in existing_ready_result.scalars().all():
            metadata = dict(existing.metadata_json or {})
            metadata["dismissed_reason"] = "Superseded by notification regeneration."
            metadata["dismissed_by"] = payload.requested_by
            metadata["dismissed_dt"] = _iso_datetime(prepared_at)
            existing.status = AUDIT_REVIEW_NOTIFICATION_STATUS_DISMISSED
            existing.metadata_json = metadata

    existing_notifications = [] if payload.regenerate else await _list_report_notifications_for_type(
        db,
        report.report_id,
        rule.notification_type,
    )
    existing_roles = {notification.recipient_role for notification in existing_notifications}
    if existing_notifications and existing_roles.issuperset(rule.recipient_roles):
        return [_build_response(notification) for notification in existing_notifications]

    subject = _build_subject(rule.priority, rating, asset, report.asset_id)
    base_metadata = _build_metadata(
        report=report,
        asset=asset,
        metrics=metrics,
        rule=rule,
        requested_by=payload.requested_by,
        is_draft_notification=is_draft_notification,
        prepared_at=prepared_at,
    )

    for role in rule.recipient_roles:
        if role in existing_roles:
            continue
        notification = AuditReviewNotification(
            report_id=report.report_id,
            job_id=report.job_id,
            asset_id=report.asset_id,
            notification_type=rule.notification_type,
            priority=rule.priority,
            rating=rating,
            recipient_role=role,
            recipient_email=_recipient_email_for_role(role, asset),
            subject=subject,
            message=_build_message(
                report=report,
                asset=asset,
                metrics=metrics,
                rule=rule,
                recipient_role=role,
                is_draft_notification=is_draft_notification,
            ),
            status=AUDIT_REVIEW_NOTIFICATION_STATUS_READY,
            delivery_channel=payload.delivery_channel,
            created_by=payload.requested_by,
            created_dt=prepared_at,
            metadata_json={**base_metadata, "recipient_role": role},
        )
        db.add(notification)

    await db.commit()
    prepared_notifications = await _list_report_notifications_for_type(db, report.report_id, rule.notification_type)
    return [_build_response(notification) for notification in prepared_notifications]


def _email_delivery_available() -> bool:
    return False


async def _mark_notification_sent_in_app(
    db: AsyncSession,
    notification: AuditReviewNotification,
    sent_by: str,
) -> SendNotificationResponse:
    now = _utc_now()
    metadata = dict(notification.metadata_json or {})
    metadata["sent_by"] = sent_by
    metadata["sent_dt"] = _iso_datetime(now)
    metadata["in_app_sent"] = True
    notification.status = AUDIT_REVIEW_NOTIFICATION_STATUS_SENT
    notification.sent_dt = now
    notification.error_message = None
    notification.metadata_json = metadata
    await db.commit()
    return SendNotificationResponse(
        notification=_build_response(notification),
        sent=True,
        message="In-app notification marked as sent.",
    )


async def send_audit_review_notification(
    db: AsyncSession,
    notification_id: uuid.UUID,
    payload: SendNotificationRequest,
) -> SendNotificationResponse:
    notification = await _require_notification(db, notification_id)

    if notification.status == AUDIT_REVIEW_NOTIFICATION_STATUS_DISMISSED:
        return SendNotificationResponse(
            notification=_build_response(notification),
            sent=False,
            skipped=True,
            message="Notification is dismissed and was not sent.",
        )
    if notification.status == AUDIT_REVIEW_NOTIFICATION_STATUS_SENT:
        return SendNotificationResponse(
            notification=_build_response(notification),
            sent=False,
            skipped=True,
            message="Notification was already sent.",
        )

    if notification.delivery_channel == AUDIT_REVIEW_NOTIFICATION_CHANNEL_IN_APP:
        return await _mark_notification_sent_in_app(db, notification, payload.sent_by)

    if notification.delivery_channel in {AUDIT_REVIEW_NOTIFICATION_CHANNEL_EMAIL, AUDIT_REVIEW_NOTIFICATION_CHANNEL_BOTH}:
        if not _email_delivery_available():
            metadata = dict(notification.metadata_json or {})
            metadata["email_configured"] = False
            metadata["email_send_attempted_by"] = payload.sent_by
            metadata["email_send_attempted_dt"] = _iso_datetime(_utc_now())
            notification.status = AUDIT_REVIEW_NOTIFICATION_STATUS_READY
            notification.error_message = EMAIL_NOT_CONFIGURED_MESSAGE
            notification.metadata_json = metadata
            await db.commit()
            return SendNotificationResponse(
                notification=_build_response(notification),
                sent=False,
                skipped=True,
                message=EMAIL_NOT_CONFIGURED_MESSAGE,
            )

    notification.status = AUDIT_REVIEW_NOTIFICATION_STATUS_FAILED
    notification.error_message = "Unsupported delivery channel."
    await db.commit()
    return SendNotificationResponse(
        notification=_build_response(notification),
        sent=False,
        failed=True,
        message="Unsupported delivery channel.",
    )


async def send_audit_review_report_notifications(
    db: AsyncSession,
    report_id: uuid.UUID,
    payload: SendNotificationRequest,
) -> SendNotificationsResponse:
    await _require_report(db, report_id)
    result = await db.execute(
        _notification_query().where(
            AuditReviewNotification.report_id == report_id,
            AuditReviewNotification.status.in_(
                [AUDIT_REVIEW_NOTIFICATION_STATUS_PENDING, AUDIT_REVIEW_NOTIFICATION_STATUS_READY]
            ),
        )
    )
    notifications = list(result.scalars().all())
    sent = 0
    failed = 0
    skipped = 0
    responses: list[AuditReviewNotificationResponse] = []
    messages: list[str] = []

    for notification in notifications:
        send_response = await send_audit_review_notification(
            db,
            notification.notification_id,
            payload,
        )
        responses.append(send_response.notification)
        if send_response.sent:
            sent += 1
        elif send_response.failed:
            failed += 1
        else:
            skipped += 1
        if send_response.message and send_response.message not in messages:
            messages.append(send_response.message)

    return SendNotificationsResponse(
        total=len(notifications),
        sent=sent,
        failed=failed,
        skipped=skipped,
        notifications=responses,
        message=" ".join(messages) if messages else None,
    )


async def list_audit_review_report_notifications(
    db: AsyncSession,
    report_id: uuid.UUID,
) -> list[AuditReviewNotificationResponse]:
    await _require_report(db, report_id)
    result = await db.execute(_notification_query().where(AuditReviewNotification.report_id == report_id))
    return [_build_response(notification) for notification in result.scalars().all()]


async def list_asset_audit_review_notifications(
    db: AsyncSession,
    asset_id: uuid.UUID,
    *,
    status: str | None = None,
    priority: str | None = None,
    limit: int = 100,
) -> list[AuditReviewNotificationResponse]:
    await _require_asset(db, asset_id)
    stmt = _notification_query().where(AuditReviewNotification.asset_id == asset_id)
    normalized_status = _normalize_status(status)
    normalized_priority = _normalize_priority(priority)
    if normalized_status:
        stmt = stmt.where(AuditReviewNotification.status == normalized_status)
    if normalized_priority:
        stmt = stmt.where(AuditReviewNotification.priority == normalized_priority)
    result = await db.execute(stmt.limit(limit))
    return [_build_response(notification) for notification in result.scalars().all()]


async def dismiss_audit_review_notification(
    db: AsyncSession,
    notification_id: uuid.UUID,
    payload: DismissNotificationRequest,
) -> AuditReviewNotificationResponse:
    notification = await _require_notification(db, notification_id)
    now = _utc_now()
    metadata = dict(notification.metadata_json or {})
    metadata["dismissed_by"] = payload.dismissed_by
    metadata["dismissed_dt"] = _iso_datetime(now)
    metadata["dismissed_reason"] = payload.reason
    notification.status = AUDIT_REVIEW_NOTIFICATION_STATUS_DISMISSED
    notification.metadata_json = metadata
    await db.commit()
    return _build_response(notification)


def escalation_summary_for_rating(rating: str | None) -> dict[str, Any] | None:
    rule = ESCALATION_MATRIX.get(_safe_str(rating).upper())
    if rule is None:
        return None
    return {
        "notification_type": rule.notification_type,
        "priority": rule.priority,
        "required_action": rule.required_action,
        "recipient_roles": list(rule.recipient_roles),
        "priority_sort": PRIORITY_ORDER.get(rule.priority, 99),
    }
