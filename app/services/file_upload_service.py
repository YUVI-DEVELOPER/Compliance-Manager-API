import re
import uuid
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile, status

from app.core.config import get_settings
from app.schemas.file_upload_schema import FileUploadResponse

ALLOWED_DOCUMENT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docm",
    ".docx",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rtf",
    ".txt",
    ".xls",
    ".xlsm",
    ".xlsx",
    ".xml",
}
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
SAFE_CATEGORY_PATTERN = re.compile(r"[^a-z0-9_-]+")


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _sanitize_filename(value: str) -> str:
    candidate = Path(value).name.strip()
    if not candidate:
        raise ServiceValidationError("file is required")
    sanitized = SAFE_FILENAME_PATTERN.sub("_", candidate)
    return sanitized.strip("._") or f"document-{uuid.uuid4().hex[:8]}"


def _sanitize_category(value: str | None) -> str:
    candidate = (value or "general").strip().lower()
    sanitized = SAFE_CATEGORY_PATTERN.sub("-", candidate)
    return sanitized.strip("-") or "general"


async def save_uploaded_document(
    request: Request,
    file: UploadFile,
    *,
    category: str | None = None,
) -> FileUploadResponse:
    settings = get_settings()
    original_file_name = _sanitize_filename(file.filename or "")
    suffix = Path(original_file_name).suffix.lower()
    if suffix not in ALLOWED_DOCUMENT_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))
        raise ServiceValidationError(f"Unsupported file type. Allowed extensions: {allowed}")

    max_bytes = settings.MAX_FILE_UPLOAD_MB * 1024 * 1024
    file_bytes = await file.read(max_bytes + 1)
    await file.close()

    if not file_bytes:
        raise ServiceValidationError("Uploaded file is empty")
    if len(file_bytes) > max_bytes:
        raise ServiceValidationError(f"Uploaded file exceeds the {settings.MAX_FILE_UPLOAD_MB} MB limit")

    safe_category = _sanitize_category(category)
    unique_name = f"{uuid.uuid4().hex}_{original_file_name}"
    if safe_category == "document-links":
        storage_root = Path(settings.FILE_STORAGE_DIR)
        target_dir = storage_root / "documents" / "staged"
        url_prefix = "filestorage"
        relative_path = f"documents/staged/{unique_name}"
    else:
        storage_root = Path(settings.FILE_UPLOAD_DIR)
        target_dir = storage_root / "documents" / safe_category
        url_prefix = "uploads"
        relative_path = f"documents/{safe_category}/{unique_name}"

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / unique_name
    target_path.write_bytes(file_bytes)

    base_url = str(request.base_url).rstrip("/")
    access_url = f"{base_url}/{url_prefix}/{relative_path}"

    return FileUploadResponse(
        file_name=unique_name,
        original_file_name=original_file_name,
        content_type=file.content_type,
        file_size=len(file_bytes),
        access_url=access_url,
        relative_path=relative_path,
    )
