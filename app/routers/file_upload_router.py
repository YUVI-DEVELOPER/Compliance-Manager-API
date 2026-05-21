from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from app.core.auth_dependencies import require_permission
from app.schemas.auth_schema import CurrentUser
from app.schemas.file_upload_schema import ApiResponse
from app.services.file_upload_service import save_uploaded_document

router = APIRouter(tags=["file-upload"])


@router.post("/file-uploads/documents", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def document_file_upload(
    request: Request,
    file: UploadFile = File(...),
    category: str = Form(default="general"),
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPLOAD")),
) -> dict[str, object]:
    data = await save_uploaded_document(request, file, category=category)
    return {
        "success": True,
        "message": "Document uploaded successfully",
        "data": data,
    }
