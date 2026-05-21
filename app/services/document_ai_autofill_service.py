from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.schemas.document_link_schema import (
    DocumentAiAutofillAnalyzeRequest,
    DocumentAiAutofillAnalyzeResponse,
)
from app.services.document_vectorization_service import _load_document_blocks, _normalize_text_for_embedding
from app.services.urs_generation_service import _build_llm_headers, _extract_chat_completion_output_text

logger = logging.getLogger(__name__)

DOCUMENT_AI_TYPES = {"URS", "FRS", "SOP", "OTHER"}
SUPPORTED_NATIVE_TEXT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MIN_NATIVE_TEXT_CHARS = 80

FIELD_DOCUMENT_TYPE = "document_type"
FIELD_EXTERNAL_DOCUMENT_ID = "external_document_id"
FIELD_DOCUMENT_VERSION = "document_version"


@dataclass(slots=True)
class FileReference:
    path: Path
    file_name: str
    original_file_name: str | None
    relative_path: str | None
    access_url: str | None


@dataclass(slots=True)
class ExtractedText:
    text: str
    heading_text: str
    method: str
    ocr_used: bool
    warnings: list[str]
    page_count: int | None = None


@dataclass(slots=True)
class Candidate:
    value: str
    confidence: float
    source: str
    details: dict[str, Any]


class DocumentAiAutofillError(HTTPException):
    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(status_code=status_code, detail=detail)


DOCUMENT_TYPE_PROFILES: dict[str, dict[str, Any]] = {
    "URS": {
        "profile": (
            "user requirement specification intended use user requirements system shall business requirements "
            "compliance requirements validation user needs acceptance criteria"
        ),
        "phrases": {
            "user requirement specification": 4.0,
            "user requirements specification": 4.0,
            "user requirements": 2.6,
            "intended use": 1.7,
            "business requirements": 1.7,
            "system shall": 1.5,
            "compliance requirements": 1.4,
            "urs": 2.4,
        },
        "filename_hints": {"urs", "user_requirement", "user_requirements"},
    },
    "FRS": {
        "profile": (
            "functional requirement specification functional requirements system functions functional behavior "
            "process logic workflows modules feature behavior interfaces"
        ),
        "phrases": {
            "functional requirement specification": 4.0,
            "functional requirements specification": 4.0,
            "functional requirements": 2.8,
            "functional behavior": 1.8,
            "process logic": 1.5,
            "system functions": 1.6,
            "workflow": 1.0,
            "frs": 2.4,
        },
        "filename_hints": {"frs", "functional_requirement", "functional_requirements"},
    },
    "SOP": {
        "profile": (
            "standard operating procedure purpose scope responsibilities procedure step-by-step instructions "
            "procedure steps roles records safety"
        ),
        "phrases": {
            "standard operating procedure": 4.2,
            "sop": 2.6,
            "purpose": 0.8,
            "scope": 0.8,
            "responsibilities": 1.2,
            "procedure": 1.4,
            "step-by-step": 1.5,
            "instructions": 1.0,
        },
        "filename_hints": {"sop", "procedure"},
    },
}

DOCUMENT_ID_LABEL_PATTERN = re.compile(
    r"\b("
    r"external\s+document\s+id|"
    r"document\s+(?:id|no\.?|number|#)|"
    r"doc(?:ument)?\s+(?:id|no\.?|number|#)|"
    r"reference\s+(?:no\.?|number|#)|"
    r"ref(?:erence)?\s+(?:no\.?|number|#)|"
    r"sop\s+(?:id|no\.?|number|#)|"
    r"urs\s+(?:id|no\.?|number|#)|"
    r"frs\s+(?:id|no\.?|number|#)"
    r")\b",
    re.IGNORECASE,
)
DOCUMENT_VERSION_LABEL_PATTERN = re.compile(
    r"\b(version\s*(?:no\.?|number|#)?|ver\.?|revision\s*(?:no\.?|number|#)?|rev\.?)\b",
    re.IGNORECASE,
)
DOCUMENT_ID_IN_FILENAME_PATTERN = re.compile(
    r"\b(?:URS|FRS|SOP)[-_ ]+[A-Z0-9][A-Z0-9._/-]*(?:[-_ ][A-Z0-9][A-Z0-9._/-]*)*\b",
    re.IGNORECASE,
)
ENTERPRISE_ID_PATTERN = re.compile(r"\b[A-Z]{2,10}-[A-Z0-9][A-Z0-9._/-]{2,}(?:-[A-Z0-9][A-Z0-9._/-]*)*\b")
VERSION_IN_FILENAME_PATTERN = re.compile(
    r"(?:^|[_\-\s])(?:v|ver|version|rev|revision)[_\-\s.]*(\d{1,3}(?:\.\d{1,3}){0,3}|[A-Z]\d?)\b",
    re.IGNORECASE,
)


def _clamp_confidence(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 2)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _safe_relative_to(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _path_under(root: Path, relative_path: str) -> Path | None:
    normalized = unquote(relative_path).strip().lstrip("/\\").replace("\\", "/")
    if not normalized:
        return None
    candidate = (root / normalized).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _candidate_paths(payload: DocumentAiAutofillAnalyzeRequest) -> list[Path]:
    settings = get_settings()
    storage_root = Path(settings.FILE_STORAGE_DIR).resolve()
    upload_root = Path(settings.FILE_UPLOAD_DIR).resolve()
    candidates: list[Path] = []

    def add_candidate(path: Path | None) -> None:
        if path is not None and path not in candidates:
            candidates.append(path)

    if payload.relative_path:
        relative = payload.relative_path.strip().replace("\\", "/").lstrip("/")
        if relative.startswith("filestorage/"):
            add_candidate(_path_under(storage_root, relative.removeprefix("filestorage/")))
        elif relative.startswith("uploads/"):
            add_candidate(_path_under(upload_root, relative.removeprefix("uploads/")))
        else:
            add_candidate(_path_under(storage_root, relative))
            add_candidate(_path_under(upload_root, relative))

    if payload.access_url:
        parsed = urlparse(payload.access_url)
        url_path = unquote(parsed.path if parsed.scheme in {"http", "https"} else payload.access_url)
        normalized = url_path.strip().lstrip("/\\").replace("\\", "/")
        if normalized.startswith("filestorage/"):
            add_candidate(_path_under(storage_root, normalized.removeprefix("filestorage/")))
        elif normalized.startswith("uploads/"):
            add_candidate(_path_under(upload_root, normalized.removeprefix("uploads/")))
        else:
            local_candidate = Path(payload.access_url)
            if local_candidate.is_file():
                add_candidate(local_candidate.resolve())

    if payload.file_name:
        safe_name = Path(payload.file_name).name
        add_candidate(_path_under(storage_root, f"documents/staged/{safe_name}"))

    return candidates


def _resolve_file_reference(payload: DocumentAiAutofillAnalyzeRequest) -> FileReference:
    candidates = _candidate_paths(payload)
    for candidate in candidates:
        if candidate.is_file():
            settings = get_settings()
            relative_path = _safe_relative_to(candidate, Path(settings.FILE_STORAGE_DIR))
            if relative_path is None:
                relative_path = _safe_relative_to(candidate, Path(settings.FILE_UPLOAD_DIR))
            return FileReference(
                path=candidate,
                file_name=candidate.name,
                original_file_name=_strip_optional(payload.original_file_name),
                relative_path=relative_path,
                access_url=_strip_optional(payload.access_url),
            )
    raise DocumentAiAutofillError("Uploaded document file is not available for AI Autofill analysis.")


def _blocks_to_text(blocks: list[Any]) -> tuple[str, str]:
    lines: list[str] = []
    headings: list[str] = []
    for block in blocks:
        text = str(getattr(block, "text", "") or "").strip()
        if not text:
            continue
        lines.append(text)
        if len(headings) < 20:
            is_heading = bool(getattr(block, "bold", False)) or 0 < float(getattr(block, "font_size", 0.0) or 0.0)
            if is_heading or len(text.split()) <= 12:
                headings.append(text)
    return "\n".join(lines).strip(), "\n".join(headings).strip()


def _load_docx_table_lines(path: Path) -> list[str]:
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX AI Autofill extraction.") from exc

    document = DocxDocument(str(path))
    lines: list[str] = []
    seen: set[str] = set()
    for table in document.tables:
        for row in table.rows:
            cells: list[str] = []
            for cell in row.cells:
                cell_text = " ".join(part.strip() for part in cell.text.splitlines() if part.strip())
                if cell_text:
                    cells.append(cell_text)
            if not cells:
                continue
            line = " | ".join(cells)
            normalized = re.sub(r"\s+", " ", line).strip().lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(line)
    return lines


def _load_native_text(path: Path) -> tuple[str, str, str, int | None]:
    extension = path.suffix.lower()
    if extension in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        headings = "\n".join(line.strip() for line in text.splitlines()[:20] if line.strip())
        return text, headings, "native-text", 1
    if extension == ".docx":
        blocks = _load_document_blocks(path)
        text, headings = _blocks_to_text(blocks)
        table_lines = _load_docx_table_lines(path)
        if table_lines:
            table_text = "\n".join(table_lines)
            text = "\n".join(part for part in (table_text, text) if part).strip()
            headings = "\n".join(part for part in (headings, table_text) if part).strip()
        page_count = max((int(getattr(block, "page", 1) or 1) for block in blocks), default=None)
        method = "native-docx+tables" if table_lines else "native-docx"
        return text, headings, method, page_count
    if extension == ".pdf":
        blocks = _load_document_blocks(path)
        text, headings = _blocks_to_text(blocks)
        page_count = max((int(getattr(block, "page", 1) or 1) for block in blocks), default=None)
        return text, headings, f"native-{extension.removeprefix('.')}", page_count
    return "", "", "unsupported", None


def _ocr_pdf_text(path: Path, warnings: list[str]) -> tuple[str, str, int | None]:
    settings = get_settings()
    if not settings.DOCUMENT_AI_AUTOFILL_USE_OCR:
        warnings.append("Native PDF text was not extractable and OCR fallback is disabled.")
        return "", "", None

    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        warnings.append("Native PDF text was not extractable; OCR fallback requires pdf2image and pytesseract.")
        return "", "", None

    try:
        max_pages = max(1, settings.DOCUMENT_AI_OCR_MAX_PAGES)
        pages = convert_from_path(str(path), first_page=1, last_page=max_pages)
        page_texts = [pytesseract.image_to_string(page).strip() for page in pages]
    except Exception as exc:  # noqa: BLE001 - OCR is a best-effort fallback.
        logger.warning("Document AI OCR fallback failed for %s: %s", path, exc)
        warnings.append("Native PDF text was not extractable and OCR fallback failed.")
        return "", "", None

    text = "\n\n".join(page_text for page_text in page_texts if page_text).strip()
    headings = "\n".join(line.strip() for line in text.splitlines()[:20] if line.strip())
    return text, headings, len(pages)


def _extract_text(file_ref: FileReference) -> ExtractedText:
    extension = file_ref.path.suffix.lower()
    warnings: list[str] = []
    if extension not in SUPPORTED_NATIVE_TEXT_EXTENSIONS:
        warnings.append(f"File type {extension or '(none)'} is not supported for AI Autofill text extraction.")
        return ExtractedText(text="", heading_text="", method="unsupported", ocr_used=False, warnings=warnings)

    try:
        text, headings, method, page_count = _load_native_text(file_ref.path)
    except Exception as exc:  # noqa: BLE001 - surface a safe analysis warning instead of failing final linking.
        logger.warning("Document AI native text extraction failed for %s: %s", file_ref.path, exc)
        warnings.append("Native text extraction failed for this document.")
        text, headings, method, page_count = "", "", "native-failed", None

    if extension == ".pdf" and len(text.strip()) < MIN_NATIVE_TEXT_CHARS:
        ocr_text, ocr_headings, ocr_page_count = _ocr_pdf_text(file_ref.path, warnings)
        if len(ocr_text.strip()) > len(text.strip()):
            return ExtractedText(
                text=ocr_text,
                heading_text=ocr_headings,
                method="ocr-pdf",
                ocr_used=True,
                warnings=warnings,
                page_count=ocr_page_count,
            )

    if not text.strip():
        warnings.append("No readable text was found in the uploaded document.")

    return ExtractedText(
        text=text,
        heading_text=headings,
        method=method,
        ocr_used=False,
        warnings=warnings,
        page_count=page_count,
    )


def _search_lines(filename: str, extracted: ExtractedText) -> list[str]:
    lines = [filename.replace("_", " ").replace("-", " ")]
    lines.extend(line.strip() for line in extracted.heading_text.splitlines() if line.strip())
    lines.extend(line.strip() for line in extracted.text.splitlines()[:160] if line.strip())
    return lines


def _clean_id_candidate(raw_value: str) -> str | None:
    value = raw_value.strip()
    value = re.split(
        r"\b(?:version|ver\.?|revision|rev\.?|document\s+name|title|upload\s+date|effective\s+date)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(r"\s{3,}|\t|\|", value, maxsplit=1)[0]
    value = value.strip(" :#=-[](){}'\"")
    value = re.sub(r"\s+", " ", value)
    if not value or len(value) < 3 or len(value) > 80:
        return None
    lowered = value.lower()
    if lowered in {"id", "number", "document", "document id", "not applicable", "n/a"}:
        return None
    if lowered.startswith(("version", "revision", "rev ", "ver ")):
        return None
    if re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", value):
        return None
    if "://" in value:
        return None
    if not re.search(r"[A-Za-z0-9]", value):
        return None
    if len(value.split()) > 6:
        return None
    return value


def _extract_value_after_label(line: str, label_match: re.Match[str]) -> str | None:
    parts = re.split(r"\s{2,}|\t|\|", line)
    if len(parts) > 1:
        for index, part in enumerate(parts):
            if label_match.group(0).lower() in part.lower() and index + 1 < len(parts):
                return parts[index + 1].strip()

    suffix = line[label_match.end() :]
    suffix = suffix.lstrip(" \t:-#")
    if suffix:
        return suffix
    return None


def _extract_external_document_id(filename: str, extracted: ExtractedText) -> Candidate | None:
    for index, line in enumerate(_search_lines(filename, extracted)):
        match = DOCUMENT_ID_LABEL_PATTERN.search(line)
        if not match:
            continue
        raw_value = _extract_value_after_label(line, match)
        if not raw_value:
            continue
        value = _clean_id_candidate(raw_value)
        if value:
            base_confidence = 0.94 if index < 40 else 0.86
            return Candidate(
                value=value,
                confidence=base_confidence,
                source="regex-label",
                details={"line": line[:300], "label": match.group(0)},
            )

    normalized_filename = Path(filename).stem.replace("__", "_")
    filename_match = DOCUMENT_ID_IN_FILENAME_PATTERN.search(normalized_filename)
    if filename_match:
        value = _clean_id_candidate(filename_match.group(0).replace("_", "-").replace(" ", "-"))
        if value and re.search(r"\d", value) and "-for-" not in value.lower():
            return Candidate(value=value, confidence=0.72, source="filename-regex", details={"file_name": filename})

    enterprise_match = ENTERPRISE_ID_PATTERN.search(extracted.heading_text or extracted.text[:4000])
    if enterprise_match:
        value = _clean_id_candidate(enterprise_match.group(0))
        if value:
            return Candidate(value=value, confidence=0.68, source="header-regex", details={"match": value})

    return None


def _clean_version_candidate(raw_value: str) -> str | None:
    value = raw_value.strip()
    value = re.split(
        r"\b(?:document\s+id|doc\s+id|document\s+name|title|effective\s+date|status|author)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(r"\s{3,}|\t|\|", value, maxsplit=1)[0]
    value = value.strip(" :#=-[](){}'\"")
    value = re.sub(r"^(?:version|ver\.?|revision|rev\.?)\s*[:#.\- ]*", "", value, flags=re.IGNORECASE)
    value = value.strip(" :#=-[](){}'\"")
    if not value or len(value) > 30:
        return None
    explicit_match = re.search(
        r"\b(?:version|ver\.?|revision|rev\.?|v)\s*[:#.\- ]*(\d{1,3}(?:\.\d{1,3}){0,3}|[A-Z]\d?)\b",
        value,
        flags=re.IGNORECASE,
    )
    if explicit_match:
        candidate = explicit_match.group(1).strip()
        return None if re.fullmatch(r"\d{4}", candidate) else candidate

    for match in re.finditer(r"\b(v?\d{1,3}(?:\.\d{1,3}){0,3}|[A-Z]\d?)\b", value, flags=re.IGNORECASE):
        candidate = match.group(1).strip()
        candidate = re.sub(r"^v(?=\d)", "", candidate, flags=re.IGNORECASE)
        if candidate.upper() in {"URS", "FRS", "SOP", "DOC", "ID", "NO"}:
            continue
        if re.fullmatch(r"\d{4}", candidate):
            continue
        if len(candidate) == 1 and candidate.isalpha() and value.strip().upper() != candidate.upper():
            continue
        return candidate
    return None


def _extract_document_version(filename: str, extracted: ExtractedText) -> Candidate | None:
    for index, line in enumerate(_search_lines(filename, extracted)):
        match = DOCUMENT_VERSION_LABEL_PATTERN.search(line)
        if not match:
            continue
        raw_value = _extract_value_after_label(line, match)
        if not raw_value:
            continue
        value = _clean_version_candidate(raw_value)
        if value:
            base_confidence = 0.92 if index < 40 else 0.84
            return Candidate(
                value=value,
                confidence=base_confidence,
                source="regex-label",
                details={"line": line[:300], "label": match.group(0)},
            )

    filename_match = VERSION_IN_FILENAME_PATTERN.search(Path(filename).stem)
    if filename_match:
        value = _clean_version_candidate(filename_match.group(1))
        if value:
            return Candidate(value=value, confidence=0.66, source="filename-regex", details={"file_name": filename})

    return None


def _tokenize(value: str) -> list[str]:
    return [part for part in re.findall(r"[a-zA-Z][a-zA-Z0-9]+", value.lower()) if len(part) > 2]


def _cosine_from_tokens(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    left_counts: dict[str, int] = {}
    right_counts: dict[str, int] = {}
    for token in left:
        left_counts[token] = left_counts.get(token, 0) + 1
    for token in right:
        right_counts[token] = right_counts.get(token, 0) + 1
    common = set(left_counts).intersection(right_counts)
    numerator = sum(left_counts[token] * right_counts[token] for token in common)
    left_norm = math.sqrt(sum(count * count for count in left_counts.values()))
    right_norm = math.sqrt(sum(count * count for count in right_counts.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


@lru_cache(maxsize=2)
def _load_classifier_embedding_model(model_source: str):
    from sentence_transformers import SentenceTransformer

    logger.info("Loading document AI classifier embedding model: %s", model_source)
    return SentenceTransformer(model_source)


def _embedding_similarity_scores(text: str, warnings: list[str]) -> dict[str, float]:
    settings = get_settings()
    if not settings.DOCUMENT_AI_USE_EMBEDDINGS:
        return {}
    try:
        model = _load_classifier_embedding_model(settings.DOCUMENT_AI_CLASSIFIER_MODEL)
        labels = ["URS", "FRS", "SOP"]
        texts = [text[:5000], *[str(DOCUMENT_TYPE_PROFILES[label]["profile"]) for label in labels]]
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        source_embedding = embeddings[0]
        scores: dict[str, float] = {}
        for label, embedding in zip(labels, embeddings[1:]):
            scores[label] = float(sum(float(a) * float(b) for a, b in zip(source_embedding, embedding)))
        return scores
    except Exception as exc:  # noqa: BLE001 - classifier falls back to deterministic scoring.
        logger.warning("Document AI embedding classifier failed: %s", exc)
        warnings.append("Embedding classifier was unavailable; rule and semantic keyword scoring were used.")
        return {}


def _classify_document_type(filename: str, extracted: ExtractedText, warnings: list[str]) -> Candidate:
    filename_text = Path(filename).stem.lower().replace("-", "_").replace(" ", "_")
    heading_text = extracted.heading_text.lower()
    content_text = _normalize_text_for_embedding(f"{filename}\n{extracted.heading_text}\n{extracted.text[:10000]}").lower()
    content_tokens = _tokenize(content_text)
    scores: dict[str, float] = {}
    score_details: dict[str, Any] = {}

    for label, profile in DOCUMENT_TYPE_PROFILES.items():
        score = 0.0
        matched_phrases: list[str] = []
        for hint in profile["filename_hints"]:
            if hint in filename_text:
                score += 3.0
                matched_phrases.append(f"filename:{hint}")
        for phrase, weight in profile["phrases"].items():
            phrase_lower = phrase.lower()
            if phrase_lower in heading_text:
                score += float(weight) * 1.5
                matched_phrases.append(phrase)
            elif phrase_lower in content_text:
                occurrences = min(content_text.count(phrase_lower), 3)
                if occurrences:
                    score += float(weight) * (0.7 + 0.2 * occurrences)
                    matched_phrases.append(phrase)
        profile_score = _cosine_from_tokens(content_tokens, _tokenize(str(profile["profile"])))
        score += profile_score * 3.0
        scores[label] = score
        score_details[label] = {"score": round(score, 3), "semantic_score": round(profile_score, 3), "matches": matched_phrases[:10]}

    embedding_scores = _embedding_similarity_scores(content_text, warnings)
    for label, embedding_score in embedding_scores.items():
        scores[label] = scores.get(label, 0.0) + max(embedding_score, 0.0) * 3.0
        score_details.setdefault(label, {})["embedding_score"] = round(embedding_score, 3)

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_label, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0
    margin = best_score - second_score

    if best_score < 1.35:
        return Candidate(
            value="OTHER",
            confidence=0.62 if extracted.text.strip() else 0.35,
            source="rules+semantic",
            details={"scores": score_details, "reason": "no document-type profile crossed the threshold"},
        )

    confidence = 0.56 + min(best_score / 14.0, 0.32) + min(margin / 10.0, 0.1)
    if margin < 0.75:
        confidence -= 0.12
    return Candidate(
        value=best_label,
        confidence=_clamp_confidence(confidence),
        source="rules+semantic" if not embedding_scores else "rules+embedding",
        details={"scores": score_details, "best_score": round(best_score, 3), "margin": round(margin, 3)},
    )


def _result_from_candidates(
    file_ref: FileReference,
    extracted: ExtractedText,
    *,
    document_type: Candidate,
    external_id: Candidate | None,
    version: Candidate | None,
    warnings: list[str],
) -> DocumentAiAutofillAnalyzeResponse:
    confidence = {
        FIELD_DOCUMENT_TYPE: _clamp_confidence(document_type.confidence),
        FIELD_EXTERNAL_DOCUMENT_ID: _clamp_confidence(external_id.confidence if external_id else 0.0),
        FIELD_DOCUMENT_VERSION: _clamp_confidence(version.confidence if version else 0.0),
    }
    source = {
        FIELD_DOCUMENT_TYPE: document_type.source,
        FIELD_EXTERNAL_DOCUMENT_ID: external_id.source if external_id else "not_found",
        FIELD_DOCUMENT_VERSION: version.source if version else "not_found",
    }
    if external_id is None:
        warnings.append("External Document ID was not found with rule-based extraction.")
    if version is None:
        warnings.append("Document Version was not found with rule-based extraction.")
    if document_type.value == "OTHER" and document_type.confidence < get_settings().DOCUMENT_AI_CONFIDENCE_THRESHOLD:
        warnings.append("Document type could not be classified confidently.")

    return DocumentAiAutofillAnalyzeResponse(
        document_type=document_type.value,
        external_document_id=external_id.value if external_id else None,
        document_version=version.value if version else None,
        confidence=confidence,
        extraction_source=source,
        warnings=list(dict.fromkeys(warnings)),
        metadata={
            "file_name": file_ref.file_name,
            "original_file_name": file_ref.original_file_name,
            "relative_path": file_ref.relative_path,
            "text_extraction_method": extracted.method,
            "ocr_used": extracted.ocr_used,
            "text_char_count": len(extracted.text),
            "page_count": extracted.page_count,
            "classifier_details": document_type.details,
            "external_document_id_details": external_id.details if external_id else None,
            "document_version_details": version.details if version else None,
        },
    )


def _extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    stripped = raw_text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _build_llm_prompt(file_ref: FileReference, extracted: ExtractedText, result: DocumentAiAutofillAnalyzeResponse) -> str:
    settings = get_settings()
    payload = {
        "task": "ValidateNow Document Linking AI Autofill fallback",
        "allowed_document_types": ["URS", "FRS", "SOP", "OTHER"],
        "rules": [
            "Return null for any field that is not explicitly supported by the filename or document text.",
            "Do not invent document IDs or versions.",
            "Use OTHER when the document is not a URS, FRS, or SOP.",
            "Return strict JSON only.",
        ],
        "required_json_shape": {
            "document_type": "URS | FRS | SOP | OTHER | null",
            "external_document_id": "string | null",
            "document_version": "string | null",
            "confidence": {
                "document_type": "number 0..1",
                "external_document_id": "number 0..1",
                "document_version": "number 0..1",
            },
        },
        "file": {
            "file_name": file_ref.file_name,
            "original_file_name": file_ref.original_file_name,
        },
        "deterministic_result": result.model_dump(),
        "text_excerpt": extracted.text[: settings.DOCUMENT_AI_MAX_TEXT_CHARS],
    }
    return json.dumps(payload, ensure_ascii=True, default=str)


async def _llm_fallback(
    file_ref: FileReference,
    extracted: ExtractedText,
    result: DocumentAiAutofillAnalyzeResponse,
) -> tuple[dict[str, Any] | None, str | None]:
    settings = get_settings()
    if not settings.DOCUMENT_AI_USE_LLM_FALLBACK or not settings.LLM_ENABLED:
        return None, None

    api_key = _strip_optional(settings.LLM_API_KEY)
    model = _strip_optional(settings.LLM_MODEL)
    if api_key is None or model is None:
        return None, "LLM fallback was skipped because LLM_API_KEY or LLM_MODEL is not configured."

    request_id = str(uuid.uuid4())
    request_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract compliance document metadata. Return strict JSON only. "
                    "Never fabricate IDs or versions. Use null when evidence is missing."
                ),
            },
            {"role": "user", "content": _build_llm_prompt(file_ref, extracted, result)},
        ],
        "temperature": 0,
    }
    max_attempts = max(1, settings.LLM_MAX_RETRIES + 1)
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                    headers=_build_llm_headers(api_key, request_id),
                    json=request_payload,
                )
                response.raise_for_status()
            response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise ValueError("LLM provider returned a non-object payload")
            content = _extract_chat_completion_output_text(response_payload)
            payload = _extract_json_payload(content)
            if payload is None:
                raise ValueError("LLM provider did not return parseable JSON")
            return payload, None
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Document AI LLM fallback attempt %s failed: %s", attempt, exc)
            if attempt >= max_attempts:
                return None, "LLM fallback failed; deterministic extraction results were kept."
            await asyncio.sleep(min(1.5 * attempt, 3.0))

    return None, "LLM fallback failed; deterministic extraction results were kept."


def _llm_confidence(payload: dict[str, Any], field: str, default: float) -> float:
    confidence = payload.get("confidence")
    if isinstance(confidence, dict):
        try:
            return _clamp_confidence(float(confidence.get(field, default)))
        except (TypeError, ValueError):
            return _clamp_confidence(default)
    return _clamp_confidence(default)


def _normalize_llm_document_type(value: Any) -> str | None:
    normalized = _strip_optional(str(value)) if value is not None else None
    if normalized is None:
        return None
    upper_value = normalized.upper().replace(" ", "_").replace("-", "_")
    return upper_value if upper_value in DOCUMENT_AI_TYPES else None


def _normalize_llm_text_value(value: Any, *, field: str) -> str | None:
    normalized = _strip_optional(str(value)) if value is not None else None
    if normalized is None:
        return None
    if field == FIELD_EXTERNAL_DOCUMENT_ID:
        return _clean_id_candidate(normalized)
    if field == FIELD_DOCUMENT_VERSION:
        return _clean_version_candidate(normalized)
    return normalized


def _merge_llm_result(result: DocumentAiAutofillAnalyzeResponse, payload: dict[str, Any]) -> None:
    threshold = get_settings().DOCUMENT_AI_CONFIDENCE_THRESHOLD

    document_type = _normalize_llm_document_type(payload.get("document_type"))
    if document_type is not None and result.confidence.get(FIELD_DOCUMENT_TYPE, 0.0) < threshold:
        result.document_type = document_type
        result.confidence[FIELD_DOCUMENT_TYPE] = _llm_confidence(payload, FIELD_DOCUMENT_TYPE, 0.7)
        result.extraction_source[FIELD_DOCUMENT_TYPE] = "llm-fallback"

    external_id = _normalize_llm_text_value(payload.get("external_document_id"), field=FIELD_EXTERNAL_DOCUMENT_ID)
    if external_id is not None and result.confidence.get(FIELD_EXTERNAL_DOCUMENT_ID, 0.0) < threshold:
        result.external_document_id = external_id
        result.confidence[FIELD_EXTERNAL_DOCUMENT_ID] = _llm_confidence(payload, FIELD_EXTERNAL_DOCUMENT_ID, 0.68)
        result.extraction_source[FIELD_EXTERNAL_DOCUMENT_ID] = "llm-fallback"

    version = _normalize_llm_text_value(payload.get("document_version"), field=FIELD_DOCUMENT_VERSION)
    if version is not None and result.confidence.get(FIELD_DOCUMENT_VERSION, 0.0) < threshold:
        result.document_version = version
        result.confidence[FIELD_DOCUMENT_VERSION] = _llm_confidence(payload, FIELD_DOCUMENT_VERSION, 0.68)
        result.extraction_source[FIELD_DOCUMENT_VERSION] = "llm-fallback"

    result.metadata["llm_fallback_used"] = True


def _needs_llm_fallback(result: DocumentAiAutofillAnalyzeResponse) -> bool:
    threshold = get_settings().DOCUMENT_AI_CONFIDENCE_THRESHOLD
    return (
        result.confidence.get(FIELD_DOCUMENT_TYPE, 0.0) < threshold
        or not result.external_document_id
        or result.confidence.get(FIELD_EXTERNAL_DOCUMENT_ID, 0.0) < threshold
        or not result.document_version
        or result.confidence.get(FIELD_DOCUMENT_VERSION, 0.0) < threshold
    )


def _run_deterministic_analysis(file_ref: FileReference) -> tuple[ExtractedText, DocumentAiAutofillAnalyzeResponse]:
    extracted = _extract_text(file_ref)
    warnings = list(extracted.warnings)
    filename = file_ref.original_file_name or file_ref.file_name
    document_type = _classify_document_type(filename, extracted, warnings)
    external_id = _extract_external_document_id(filename, extracted)
    version = _extract_document_version(filename, extracted)
    result = _result_from_candidates(
        file_ref,
        extracted,
        document_type=document_type,
        external_id=external_id,
        version=version,
        warnings=warnings,
    )
    result.metadata["llm_fallback_used"] = False
    return extracted, result


async def analyze_document_link_ai_autofill(
    payload: DocumentAiAutofillAnalyzeRequest,
) -> DocumentAiAutofillAnalyzeResponse:
    settings = get_settings()
    if not settings.DOCUMENT_AI_AUTOFILL_ENABLED:
        raise DocumentAiAutofillError("Document AI Autofill is disabled by configuration.")

    file_ref = _resolve_file_reference(payload)
    extracted, result = await asyncio.to_thread(_run_deterministic_analysis, file_ref)

    if _needs_llm_fallback(result):
        llm_payload, llm_warning = await _llm_fallback(file_ref, extracted, result)
        if llm_payload is not None:
            _merge_llm_result(result, llm_payload)
        elif llm_warning:
            result.warnings.append(llm_warning)

    result.warnings = list(dict.fromkeys(result.warnings))
    return result
