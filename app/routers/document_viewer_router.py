from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response

from app.core.auth_dependencies import require_permission
from app.core.config import get_settings
from app.schemas.auth_schema import CurrentUser
from app.services.document_viewer_service import (
    build_document_original_response,
    build_document_preview_response,
    build_storage_file_response,
)

router = APIRouter(tags=["document-viewer"])


@router.get("/document-viewer/preview")
async def document_viewer_preview(
    source_url: str = Query(..., min_length=1),
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
) -> Response:
    return build_document_preview_response(source_url)


@router.get("/document-viewer/original")
async def document_viewer_original(
    source_url: str = Query(..., min_length=1),
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
) -> FileResponse:
    return build_document_original_response(source_url)


@router.get("/uploads/{storage_path:path}")
async def protected_upload_file(
    storage_path: str,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
) -> FileResponse:
    return build_storage_file_response(Path(get_settings().FILE_UPLOAD_DIR), storage_path)


@router.get("/filestorage/{storage_path:path}")
async def protected_filestorage_file(
    storage_path: str,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
) -> FileResponse:
    return build_storage_file_response(Path(get_settings().FILE_STORAGE_DIR), storage_path)
