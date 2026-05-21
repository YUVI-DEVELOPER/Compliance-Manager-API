import re
import uuid
from difflib import SequenceMatcher
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.release_impact_assessment import ReleaseImpactAssessment
from app.schemas.release_assessment_schema import (
    ReleaseImpactAssessmentDownloadResponse,
    ReleaseImpactAssessmentResponse,
)
from app.services.release_service import ServiceConflictError, ServiceNotFoundError, ServiceValidationError

VALIDATION_IMPACT_KEYWORDS = (
    "validation",
    "qualification",
    "protocol",
    "configuration",
    "interface",
    "workflow",
    "permission",
    "audit",
    "report",
    "calculation",
    "formula",
    "threshold",
    "regulatory",
    "sop",
    "integration",
)
MAX_REPORTED_CHANGE_ENTRIES = 10


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized_lines: list[str] = []
    previous_blank = False
    for line in text.split("\n"):
        cleaned_line = re.sub(r"\s+", " ", line).strip()
        if not cleaned_line:
            if normalized_lines and not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(cleaned_line)
        previous_blank = False
    return "\n".join(normalized_lines).strip()


def _count_non_empty_lines(lines: list[str]) -> int:
    return sum(1 for line in lines if line.strip())


def _line_range(start_index: int, end_index: int, lines: list[str]) -> dict[str, int] | None:
    relevant_lines = [idx for idx in range(start_index, end_index) if idx < len(lines) and lines[idx].strip()]
    if not relevant_lines:
        return None
    return {
        "start": relevant_lines[0] + 1,
        "end": relevant_lines[-1] + 1,
    }


def _extract_matched_keywords(*chunks: list[str]) -> list[str]:
    haystack = "\n".join(line for chunk in chunks for line in chunk).lower()
    return sorted({keyword for keyword in VALIDATION_IMPACT_KEYWORDS if keyword in haystack})


def _build_diff_summary(previous_text: str, current_text: str) -> tuple[dict[str, object], str]:
    previous_lines = previous_text.splitlines()
    current_lines = current_text.splitlines()
    matcher = SequenceMatcher(None, previous_lines, current_lines)

    change_entries: list[dict[str, object]] = []
    matched_keywords: set[str] = set()
    added_lines = 0
    removed_lines = 0
    replaced_lines = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        previous_chunk = previous_lines[i1:i2]
        current_chunk = current_lines[j1:j2]
        previous_non_empty = [line for line in previous_chunk if line.strip()]
        current_non_empty = [line for line in current_chunk if line.strip()]

        if tag == "insert":
            added_lines += _count_non_empty_lines(current_chunk)
        elif tag == "delete":
            removed_lines += _count_non_empty_lines(previous_chunk)
        else:
            replaced_lines += max(_count_non_empty_lines(previous_chunk), _count_non_empty_lines(current_chunk))

        chunk_keywords = _extract_matched_keywords(previous_non_empty, current_non_empty)
        matched_keywords.update(chunk_keywords)
        change_entries.append(
            {
                "change_type": tag,
                "previous_line_range": _line_range(i1, i2, previous_lines),
                "current_line_range": _line_range(j1, j2, current_lines),
                "previous_excerpt": previous_non_empty[:5],
                "current_excerpt": current_non_empty[:5],
                "matched_keywords": chunk_keywords,
            }
        )

    total_changed_lines = added_lines + removed_lines + replaced_lines
    keyword_count = len(matched_keywords)
    if keyword_count >= 3 or total_changed_lines >= 25:
        impact_level = "HIGH"
    elif keyword_count >= 1 or total_changed_lines >= 8 or len(change_entries) >= 3:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"

    diff_summary: dict[str, object] = {
        "comparison_type": "DIFF",
        "similarity_ratio": round(matcher.ratio(), 4),
        "total_changed_lines": total_changed_lines,
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "replaced_lines": replaced_lines,
        "changed_segments": len(change_entries),
        "matched_keywords": sorted(matched_keywords),
        "changes": change_entries[:MAX_REPORTED_CHANGE_ENTRIES],
        "truncated_changes": max(len(change_entries) - MAX_REPORTED_CHANGE_ENTRIES, 0),
    }
    return diff_summary, impact_level


def _format_line_range(line_range: dict[str, int] | None) -> str:
    if line_range is None:
        return "n/a"
    if line_range["start"] == line_range["end"]:
        return str(line_range["start"])
    return f'{line_range["start"]}-{line_range["end"]}'


def _format_excerpt(lines: list[str]) -> str:
    if not lines:
        return "_No content_"
    return "\n".join(f"- {line}" for line in lines)


def _build_baseline_summary(current_release: AssetRelease, previous_release: AssetRelease | None) -> dict[str, object]:
    return {
        "comparison_type": "BASELINE",
        "has_previous_release": previous_release is not None,
        "message": (
            "No previous release documentation was available for comparison."
            if previous_release is None
            else "The previous release exists, but it does not contain documentation_text for comparison."
        ),
        "matched_keywords": [],
        "changes": [],
        "total_changed_lines": 0,
    }


def _build_baseline_report(
    current_release: AssetRelease,
    previous_release: AssetRelease | None,
    diff_summary: dict[str, object],
    generated_dt: datetime,
) -> str:
    asset_name = current_release.asset.asset_name if current_release.asset is not None else str(current_release.asset_id)
    previous_version = previous_release.version if previous_release is not None else "None"
    source_url = current_release.documentation_source_url or "Manual entry"

    return "\n".join(
        [
            "# Release Impact Assessment",
            "",
            "## Summary",
            f"- Asset: {asset_name}",
            f"- Current release: {current_release.version}",
            f"- Previous release: {previous_version}",
            "- Impact level: Not rated",
            f"- Generated at: {generated_dt.isoformat()}",
            "",
            "## Documentation Source",
            f"- Documentation mode: {current_release.documentation_mode}",
            f"- Documentation source URL: {source_url}",
            "",
            "## Baseline Assessment",
            str(diff_summary["message"]),
            "",
            "## Recommendation",
            "Perform an initial validation review of the current release documentation before relying on automated change impact.",
        ]
    )


def _build_diff_report(
    current_release: AssetRelease,
    previous_release: AssetRelease,
    diff_summary: dict[str, object],
    impact_level: str,
    generated_dt: datetime,
) -> str:
    asset_name = current_release.asset.asset_name if current_release.asset is not None else str(current_release.asset_id)
    matched_keywords = diff_summary["matched_keywords"]
    keyword_text = ", ".join(matched_keywords) if matched_keywords else "None detected"

    report_lines = [
        "# Release Impact Assessment",
        "",
        "## Summary",
        f"- Asset: {asset_name}",
        f"- Current release: {current_release.version}",
        f"- Previous release: {previous_release.version}",
        f"- Impact level: {impact_level}",
        f"- Generated at: {generated_dt.isoformat()}",
        "",
        "## Comparison Metrics",
        f'- Similarity ratio: {diff_summary["similarity_ratio"]}',
        f'- Total changed lines: {diff_summary["total_changed_lines"]}',
        f'- Added lines: {diff_summary["added_lines"]}',
        f'- Removed lines: {diff_summary["removed_lines"]}',
        f'- Replaced lines: {diff_summary["replaced_lines"]}',
        f'- Changed segments: {diff_summary["changed_segments"]}',
        f"- Validation-impact keywords: {keyword_text}",
        "",
        "## Assessment",
        "Changes were identified by normalized line-level comparison of release documentation text.",
    ]

    changes = diff_summary["changes"]
    if not changes:
        report_lines.extend(
            [
                "",
                "## Detailed Changes",
                "No material line-level differences were detected after normalization.",
            ]
        )
        return "\n".join(report_lines)

    report_lines.extend(["", "## Detailed Changes"])
    for index, change in enumerate(changes, start=1):
        report_lines.extend(
            [
                f"### Change {index}",
                f'- Change type: {change["change_type"]}',
                f'- Previous lines: {_format_line_range(change["previous_line_range"])}',
                f'- Current lines: {_format_line_range(change["current_line_range"])}',
                f'- Matched keywords: {", ".join(change["matched_keywords"]) if change["matched_keywords"] else "None"}',
                "- Previous excerpt:",
                _format_excerpt(change["previous_excerpt"]),
                "- Current excerpt:",
                _format_excerpt(change["current_excerpt"]),
                "",
            ]
        )

    truncated_changes = diff_summary["truncated_changes"]
    if truncated_changes:
        report_lines.append(f"_Additional changed segments not shown: {truncated_changes}_")

    return "\n".join(report_lines).strip()


def _build_report_title(release: AssetRelease) -> str:
    asset_name = release.asset.asset_name if release.asset is not None else str(release.asset_id)
    return f"Release Impact Assessment - {asset_name} - {release.version}"[:250]


def _sanitize_file_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "release-impact-assessment"


def _assessment_query() -> Select[tuple[ReleaseImpactAssessment]]:
    return select(ReleaseImpactAssessment).options(
        selectinload(ReleaseImpactAssessment.release).selectinload(AssetRelease.asset),
        selectinload(ReleaseImpactAssessment.previous_release),
    )


async def _get_release_model_by_id(db: AsyncSession, release_id: uuid.UUID) -> AssetRelease | None:
    stmt = (
        select(AssetRelease)
        .options(selectinload(AssetRelease.asset).selectinload(Asset.supplier))
        .where(AssetRelease.release_id == release_id)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_latest_assessment_model_by_release_id(
    db: AsyncSession, release_id: uuid.UUID
) -> ReleaseImpactAssessment | None:
    stmt = (
        _assessment_query()
        .where(ReleaseImpactAssessment.release_id == release_id)
        .order_by(ReleaseImpactAssessment.generated_dt.desc(), ReleaseImpactAssessment.assessment_id.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


def _build_assessment_response(assessment: ReleaseImpactAssessment) -> ReleaseImpactAssessmentResponse:
    return ReleaseImpactAssessmentResponse(
        assessment_id=assessment.assessment_id,
        release_id=assessment.release_id,
        previous_release_id=assessment.previous_release_id,
        report_title=assessment.report_title,
        report_content=assessment.report_content,
        report_format=assessment.report_format,
        diff_summary=assessment.diff_summary,
        impact_level=assessment.impact_level,
        generated_dt=assessment.generated_dt,
        created_by=assessment.created_by,
    )


async def get_previous_release_for_asset(
    db: AsyncSession, current_release: AssetRelease
) -> AssetRelease | None:
    stmt = (
        select(AssetRelease)
        .options(selectinload(AssetRelease.asset))
        .where(
            AssetRelease.asset_id == current_release.asset_id,
            AssetRelease.created_dt < current_release.created_dt,
        )
        .order_by(AssetRelease.created_dt.desc(), AssetRelease.version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def generate_impact_assessment_for_release(
    db: AsyncSession,
    release_id: uuid.UUID,
    *,
    created_by: str | None = None,
    commit: bool = True,
) -> ReleaseImpactAssessmentResponse:
    current_release = await _get_release_model_by_id(db, release_id)
    if current_release is None:
        raise ServiceNotFoundError("Release not found")

    current_text = _normalize_text(current_release.documentation_text)
    if not current_text:
        raise ServiceValidationError("Current release documentation_text is required to generate an impact assessment")

    previous_release = await get_previous_release_for_asset(db, current_release)
    previous_text = _normalize_text(previous_release.documentation_text if previous_release is not None else None)
    generated_dt = datetime.now(UTC)

    if previous_release is None or not previous_text:
        diff_summary = _build_baseline_summary(current_release, previous_release)
        report_content = _build_baseline_report(current_release, previous_release, diff_summary, generated_dt)
        impact_level = None
    else:
        diff_summary, impact_level = _build_diff_summary(previous_text, current_text)
        report_content = _build_diff_report(current_release, previous_release, diff_summary, impact_level, generated_dt)

    assessment = ReleaseImpactAssessment(
        release_id=current_release.release_id,
        previous_release_id=previous_release.release_id if previous_release is not None else None,
        report_title=_build_report_title(current_release),
        report_content=report_content,
        report_format="MARKDOWN",
        diff_summary=diff_summary,
        impact_level=impact_level,
        generated_dt=generated_dt,
        created_by=created_by or current_release.modified_by or current_release.created_by,
    )
    db.add(assessment)

    try:
        if commit:
            await db.commit()
        else:
            await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to generate impact assessment") from exc

    if commit:
        refreshed_assessment = await _get_latest_assessment_model_by_release_id(db, release_id)
        if refreshed_assessment is None:
            raise ServiceNotFoundError("Impact assessment not found after generation")
        return _build_assessment_response(refreshed_assessment)

    return _build_assessment_response(assessment)


async def get_latest_assessment_for_release(
    db: AsyncSession, release_id: uuid.UUID
) -> ReleaseImpactAssessmentResponse:
    release = await _get_release_model_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")

    assessment = await _get_latest_assessment_model_by_release_id(db, release_id)
    if assessment is None:
        raise ServiceNotFoundError("Impact assessment not found for this release")
    return _build_assessment_response(assessment)


async def download_assessment_for_release(
    db: AsyncSession, release_id: uuid.UUID
) -> ReleaseImpactAssessmentDownloadResponse:
    release = await _get_release_model_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")

    assessment = await _get_latest_assessment_model_by_release_id(db, release_id)
    if assessment is None:
        raise ServiceNotFoundError("Impact assessment not found for this release")

    file_stem = _sanitize_file_name(f"{release.version}-impact-assessment")
    return ReleaseImpactAssessmentDownloadResponse(
        file_name=f"{file_stem}.md",
        media_type="text/markdown",
        report_content=assessment.report_content,
        generated_dt=assessment.generated_dt,
    )
