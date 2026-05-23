from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit_actions
from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.file_upload_schema import ApiResponse
from app.services.audit_log_service import create_audit_log
from app.services.file_upload_service import save_uploaded_document

router = APIRouter(tags=["file-upload"])


@router.post("/file-uploads/documents", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def document_file_upload(
    request: Request,
    file: UploadFile = File(...),
    category: str = Form(default="general"),
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPLOAD")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await save_uploaded_document(request, file, category=category)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Document Management",
        entity_name="Document",
        table_name="file_upload",
        record_id=data.file_name,
        action=audit_actions.DOCUMENT_UPLOADED,
        event_description="Document uploaded",
        new_data=data.model_dump(mode="json"),
    )
    await db.commit()
    return {
        "success": True,
        "message": "Document uploaded successfully",
        "data": data,
    }
