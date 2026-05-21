import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.supplier_evaluation_schema import (
    ApiResponse,
    EvaluationRequirementItemCreate,
    EvaluationRequirementItemUpdate,
    EvaluationRequirementSeedRequest,
    SupplierEvaluationAnalysisRunRequest,
    SupplierEvaluationCreate,
    SupplierEvaluationResponseCreate,
    SupplierEvaluationResponseSubmitRequest,
    SupplierEvaluationResponseUpdate,
    SupplierRequirementResponseBulkSaveRequest,
    SupplierRequirementResponseCreate,
    SupplierRequirementResponseUpdate,
    SupplierEvaluationUpdate,
    SupplierEvaluationWorkflowActionRequest,
    SupplierResponseDocumentCreate,
)
from app.services.supplier_evaluation_service import (
    add_supplier_evaluation_responses,
    create_supplier_evaluation,
    create_supplier_response_document,
    delete_supplier_response_document,
    get_supplier_evaluation_by_id,
    get_supplier_evaluation_response_by_id,
    get_supplier_evaluation_responses,
    get_supplier_evaluations,
    get_supplier_response_documents,
    lock_supplier_evaluation,
    open_supplier_evaluation,
    submit_supplier_evaluation_response,
    update_supplier_evaluation,
    update_supplier_evaluation_response,
)
from app.services.supplier_evaluation_analysis_service import (
    get_supplier_evaluation_analysis,
    get_supplier_evaluation_comparison,
    run_supplier_evaluation_analysis,
)
from app.services.supplier_requirement_service import (
    bulk_save_supplier_requirement_responses,
    create_evaluation_requirement_item,
    create_supplier_requirement_response,
    delete_evaluation_requirement_item,
    delete_supplier_requirement_response,
    get_supplier_evaluation_requirements,
    get_supplier_response_requirement_matrix,
    seed_supplier_evaluation_requirements,
    update_evaluation_requirement_item,
    update_supplier_requirement_response,
)

router = APIRouter(tags=["supplier-evaluation"], dependencies=[Depends(require_permission("SUPPLIER_VIEW"))])


@router.get("/supplier-evaluations", response_model=ApiResponse)
async def supplier_evaluation_list(
    asset_uuid: uuid.UUID | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_evaluations(db, asset_uuid=asset_uuid, status_value=status_value)
    return {
        "success": True,
        "message": "Supplier evaluations fetched successfully",
        "data": data,
    }


@router.get("/supplier-evaluations/{evaluation_id}", response_model=ApiResponse)
async def supplier_evaluation_detail(
    evaluation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_evaluation_by_id(db, evaluation_id)
    return {
        "success": True,
        "message": "Supplier evaluation fetched successfully",
        "data": data,
    }


@router.post(
    "/supplier-evaluations",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("SUPPLIER_CREATE"))],
)
async def supplier_evaluation_create(
    payload: SupplierEvaluationCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_supplier_evaluation(db, payload)
    return {
        "success": True,
        "message": "Supplier evaluation created successfully",
        "data": data,
    }


@router.put(
    "/supplier-evaluations/{evaluation_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_evaluation_update(
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_supplier_evaluation(db, evaluation_id, payload)
    return {
        "success": True,
        "message": "Supplier evaluation updated successfully",
        "data": data,
    }


@router.post(
    "/supplier-evaluations/{evaluation_id}/open",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_evaluation_open(
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationWorkflowActionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await open_supplier_evaluation(db, evaluation_id, payload)
    return {
        "success": True,
        "message": "Supplier evaluation opened successfully",
        "data": data,
    }


@router.post(
    "/supplier-evaluations/{evaluation_id}/lock",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_evaluation_lock(
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationWorkflowActionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await lock_supplier_evaluation(db, evaluation_id, payload)
    return {
        "success": True,
        "message": "Supplier evaluation locked successfully",
        "data": data,
    }


@router.post(
    "/supplier-evaluations/{evaluation_id}/run-analysis",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_evaluation_run_analysis(
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationAnalysisRunRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await run_supplier_evaluation_analysis(db, evaluation_id, payload)
    return {
        "success": True,
        "message": "Supplier evaluation analysis run finished",
        "data": data,
    }


@router.get("/supplier-evaluations/{evaluation_id}/analysis", response_model=ApiResponse)
async def supplier_evaluation_analysis(
    evaluation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_evaluation_analysis(db, evaluation_id)
    return {
        "success": True,
        "message": "Supplier evaluation analysis history fetched successfully",
        "data": data,
    }


@router.get("/supplier-evaluations/{evaluation_id}/comparison", response_model=ApiResponse)
async def supplier_evaluation_comparison(
    evaluation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_evaluation_comparison(db, evaluation_id)
    return {
        "success": True,
        "message": "Supplier evaluation comparison fetched successfully",
        "data": data,
    }


@router.get("/supplier-evaluations/{evaluation_id}/responses", response_model=ApiResponse)
async def supplier_evaluation_response_list(
    evaluation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_evaluation_responses(db, evaluation_id)
    return {
        "success": True,
        "message": "Supplier evaluation responses fetched successfully",
        "data": data,
    }


@router.get("/supplier-evaluations/{evaluation_id}/requirements", response_model=ApiResponse)
async def supplier_evaluation_requirement_list(
    evaluation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_evaluation_requirements(db, evaluation_id)
    return {
        "success": True,
        "message": "Evaluation requirements fetched successfully",
        "data": data,
    }


@router.post(
    "/supplier-evaluations/{evaluation_id}/requirements/seed",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_evaluation_requirement_seed(
    evaluation_id: uuid.UUID,
    payload: EvaluationRequirementSeedRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await seed_supplier_evaluation_requirements(db, evaluation_id, payload)
    return {
        "success": True,
        "message": "Evaluation requirements seeded successfully",
        "data": data,
    }


@router.post(
    "/supplier-evaluations/{evaluation_id}/requirements",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_evaluation_requirement_create(
    evaluation_id: uuid.UUID,
    payload: EvaluationRequirementItemCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_evaluation_requirement_item(db, evaluation_id, payload)
    return {
        "success": True,
        "message": "Evaluation requirement created successfully",
        "data": data,
    }


@router.post(
    "/supplier-evaluations/{evaluation_id}/responses",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_evaluation_response_create(
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationResponseCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await add_supplier_evaluation_responses(db, evaluation_id, payload)
    return {
        "success": True,
        "message": "Supplier evaluation responses created successfully",
        "data": data,
    }


@router.get("/supplier-responses/{response_id}", response_model=ApiResponse)
async def supplier_response_detail(
    response_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_evaluation_response_by_id(db, response_id)
    return {
        "success": True,
        "message": "Supplier response fetched successfully",
        "data": data,
    }


@router.put(
    "/supplier-responses/{response_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_response_update(
    response_id: uuid.UUID,
    payload: SupplierEvaluationResponseUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_supplier_evaluation_response(db, response_id, payload)
    return {
        "success": True,
        "message": "Supplier response updated successfully",
        "data": data,
    }


@router.post(
    "/supplier-responses/{response_id}/submit",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_response_submit(
    response_id: uuid.UUID,
    payload: SupplierEvaluationResponseSubmitRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await submit_supplier_evaluation_response(db, response_id, payload)
    return {
        "success": True,
        "message": "Supplier response submitted successfully",
        "data": data,
    }


@router.get("/supplier-responses/{response_id}/requirements", response_model=ApiResponse)
async def supplier_response_requirement_list(
    response_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_response_requirement_matrix(db, response_id)
    return {
        "success": True,
        "message": "Supplier requirement responses fetched successfully",
        "data": data,
    }


@router.post(
    "/supplier-responses/{response_id}/requirements",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_response_requirement_create(
    response_id: uuid.UUID,
    payload: SupplierRequirementResponseCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_supplier_requirement_response(db, response_id, payload)
    return {
        "success": True,
        "message": "Supplier requirement response created successfully",
        "data": data,
    }


@router.put(
    "/supplier-responses/{response_id}/requirements/bulk-save",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_response_requirement_bulk_save(
    response_id: uuid.UUID,
    payload: SupplierRequirementResponseBulkSaveRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await bulk_save_supplier_requirement_responses(db, response_id, payload)
    return {
        "success": True,
        "message": "Supplier requirement responses saved successfully",
        "data": data,
    }


@router.get("/supplier-responses/{response_id}/documents", response_model=ApiResponse)
async def supplier_response_document_list(
    response_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_response_documents(db, response_id)
    return {
        "success": True,
        "message": "Supplier response documents fetched successfully",
        "data": data,
    }


@router.post(
    "/supplier-responses/{response_id}/documents",
    response_model=ApiResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("DOCUMENT_UPLOAD"))],
)
async def supplier_response_document_create(
    response_id: uuid.UUID,
    payload: SupplierResponseDocumentCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_supplier_response_document(db, response_id, payload)
    return {
        "success": True,
        "message": "Supplier response document created successfully",
        "data": data,
    }


@router.delete(
    "/supplier-response-documents/{document_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("DOCUMENT_DELETE"))],
)
async def supplier_response_document_delete(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_supplier_response_document(db, document_id)
    return {
        "success": True,
        "message": "Supplier response document deleted successfully",
        "data": {"document_id": document_id},
    }


@router.put(
    "/evaluation-requirements/{requirement_item_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_evaluation_requirement_update(
    requirement_item_id: uuid.UUID,
    payload: EvaluationRequirementItemUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_evaluation_requirement_item(db, requirement_item_id, payload)
    return {
        "success": True,
        "message": "Evaluation requirement updated successfully",
        "data": data,
    }


@router.delete(
    "/evaluation-requirements/{requirement_item_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_DELETE"))],
)
async def supplier_evaluation_requirement_delete(
    requirement_item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_evaluation_requirement_item(db, requirement_item_id)
    return {
        "success": True,
        "message": "Evaluation requirement deleted successfully",
        "data": {"requirement_item_id": requirement_item_id},
    }


@router.put(
    "/supplier-requirement-responses/{requirement_response_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_UPDATE"))],
)
async def supplier_requirement_response_update(
    requirement_response_id: uuid.UUID,
    payload: SupplierRequirementResponseUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_supplier_requirement_response(db, requirement_response_id, payload)
    return {
        "success": True,
        "message": "Supplier requirement response updated successfully",
        "data": data,
    }


@router.delete(
    "/supplier-requirement-responses/{requirement_response_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permission("SUPPLIER_DELETE"))],
)
async def supplier_requirement_response_delete(
    requirement_response_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_supplier_requirement_response(db, requirement_response_id)
    return {
        "success": True,
        "message": "Supplier requirement response deleted successfully",
        "data": {"requirement_response_id": requirement_response_id},
    }
