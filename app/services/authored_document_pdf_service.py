from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from io import BytesIO
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset_release import AssetRelease
from app.models.authored_document import AuthoredDocument
from app.services.authored_document_service import ServiceNotFoundError

PDF_MEDIA_TYPE = "application/pdf"
APPLICATION_NAME = "ValidateNow / Compliance Manager"
DOCUMENT_TITLE = "User Requirements Specification"


@dataclass(frozen=True)
class AuthoredDocumentPdf:
    file_name: str
    media_type: str
    content: bytes


def _safe_text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _safe_filename(value: Any, fallback: str = "authored-urs") -> str:
    text = _safe_text(value, fallback)
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-")
    return text or fallback


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return resolved.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _extract_generation_context(source_context: dict[str, Any] | None) -> dict[str, Any]:
    return source_context if isinstance(source_context, dict) else {}


def _markdown_blocks(content: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_paragraph: list[str] = []
    bullet_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal current_paragraph
        if current_paragraph:
            blocks.append({"type": "paragraph", "text": " ".join(current_paragraph).strip()})
            current_paragraph = []

    def flush_bullets() -> None:
        nonlocal bullet_items
        if bullet_items:
            blocks.append({"type": "bullets", "items": bullet_items})
            bullet_items = []

    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_bullets()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_bullets()
            blocks.append({"type": "heading", "level": len(heading.group(1)), "text": heading.group(2).strip()})
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            bullet_items.append(bullet.group(1).strip())
            continue

        flush_bullets()
        current_paragraph.append(line)

    flush_paragraph()
    flush_bullets()
    return blocks


def _inline_markup(text: Any) -> str:
    escaped = escape(_safe_text(text, ""))
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`(.+?)`", r'<font name="Courier">\1</font>', escaped)
    return escaped


def _paragraph(text: Any, style: Any) -> Any:
    from reportlab.platypus import Paragraph

    return Paragraph(_inline_markup(text), style)


def _table(headers: list[str], rows: list[list[Any]], widths: list[float], styles: dict[str, Any]) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    table_rows = [[_paragraph(header, styles["table_header"]) for header in headers]]
    for row in rows:
        padded = [*row, *([""] * max(0, len(headers) - len(row)))]
        table_rows.append([_paragraph(cell, styles["table_cell"]) for cell in padded[: len(headers)]])

    table = Table(table_rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _draw_footer(canvas: Any, doc: Any, document_number: str, generated_dt: str) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(0.33, 0.37, 0.43)
    canvas.drawString(doc.leftMargin, 0.42 * 72, "Controlled draft")
    canvas.drawCentredString(doc.pagesize[0] / 2, 0.42 * 72, generated_dt)
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.42 * 72, f"{document_number} | Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _build_pdf(document: AuthoredDocument) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import ListFlowable, ListItem, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise RuntimeError("ReportLab is required for authored document PDF rendering") from exc

    release = document.release
    asset = document.asset or (release.asset if release is not None else None)
    context = _extract_generation_context(document.source_context_json)
    asset_context = context.get("asset") if isinstance(context.get("asset"), dict) else {}
    generated_dt = _format_datetime(document.modified_dt or document.created_dt)
    document_number = _safe_text(document.title, str(document.authored_document_id))
    file_title = _safe_text(document.title, DOCUMENT_TITLE)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=0.62 * inch,
        leftMargin=0.62 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.78 * inch,
        title=file_title,
        author=APPLICATION_NAME,
        pageCompression=0,
    )

    base = getSampleStyleSheet()
    styles = {
        "app": ParagraphStyle("App", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#64748b")),
        "title": ParagraphStyle("Title", parent=base["Title"], fontSize=18, leading=23, alignment=TA_CENTER, textColor=colors.HexColor("#0f172a")),
        "subtitle": ParagraphStyle("Subtitle", parent=base["Normal"], fontSize=9, leading=12, alignment=TA_CENTER, textColor=colors.HexColor("#475569")),
        "section": ParagraphStyle("Section", parent=base["Heading2"], fontSize=12.5, leading=15, spaceBefore=13, spaceAfter=5, textColor=colors.HexColor("#1e3a8a")),
        "subsection": ParagraphStyle("Subsection", parent=base["Heading3"], fontSize=10.5, leading=13, spaceBefore=9, spaceAfter=4, textColor=colors.HexColor("#0f172a")),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontSize=9.2, leading=13.2, spaceAfter=6),
        "bullet": ParagraphStyle("Bullet", parent=base["BodyText"], fontSize=9, leading=12.5),
        "table_header": ParagraphStyle("TableHeader", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10),
        "table_cell": ParagraphStyle("TableCell", parent=base["Normal"], fontSize=8, leading=10),
    }

    meta_rows = [
        ["Document Title", document.title],
        ["Document Type", document.document_type],
        ["Status", document.status],
        ["Template", document.template.template_name if document.template is not None else "-"],
        ["Asset Name", getattr(asset, "asset_name", None) or asset_context.get("asset_name")],
        ["Asset ID", getattr(asset, "asset_id", None) or asset_context.get("asset_id")],
        ["Release", release.version if release is not None else "Asset level"],
        ["Generated / Updated", generated_dt],
        ["Reviewer", document.reviewer_name],
        ["Approver", document.approver_name],
    ]

    flow: list[Any] = [
        _paragraph(APPLICATION_NAME, styles["app"]),
        _paragraph(DOCUMENT_TITLE, styles["title"]),
        _paragraph(file_title, styles["subtitle"]),
        Spacer(1, 8),
        _table(["Field", "Value"], meta_rows, [1.85 * inch, 4.65 * inch], styles),
        Spacer(1, 8),
    ]

    for block in _markdown_blocks(document.content or ""):
        if block["type"] == "heading":
            level = int(block["level"])
            style = styles["title"] if level == 1 and len(flow) < 5 else styles["section"] if level <= 2 else styles["subsection"]
            flow.append(_paragraph(block["text"], style))
            continue
        if block["type"] == "bullets":
            flow.append(
                ListFlowable(
                    [ListItem(_paragraph(item, styles["bullet"]), leftIndent=12) for item in block["items"]],
                    bulletType="bullet",
                    leftIndent=16,
                    bulletFontSize=6,
                )
            )
            flow.append(Spacer(1, 4))
            continue
        flow.append(_paragraph(block["text"], styles["body"]))

    if not document.content.strip():
        flow.append(_paragraph("No authored content is available for this draft.", styles["body"]))

    doc.build(flow, onFirstPage=lambda canvas, current_doc: _draw_footer(canvas, current_doc, document_number, generated_dt), onLaterPages=lambda canvas, current_doc: _draw_footer(canvas, current_doc, document_number, generated_dt))
    return buffer.getvalue()


async def build_authored_document_pdf(db: AsyncSession, authored_document_id: uuid.UUID) -> AuthoredDocumentPdf:
    result = await db.execute(
        select(AuthoredDocument)
        .options(
            selectinload(AuthoredDocument.template),
            selectinload(AuthoredDocument.asset),
            selectinload(AuthoredDocument.release),
            selectinload(AuthoredDocument.release).selectinload(AssetRelease.asset),
        )
        .where(AuthoredDocument.authored_document_id == authored_document_id)
    )
    document = result.scalars().first()
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    file_name = f"{_safe_filename(document.title)}-{document.authored_document_id}.pdf"
    return AuthoredDocumentPdf(file_name=file_name, media_type=PDF_MEDIA_TYPE, content=_build_pdf(document))
