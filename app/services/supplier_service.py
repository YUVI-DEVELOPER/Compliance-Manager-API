import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.models.supplier import Supplier
from app.schemas.supplier_schema import SupplierCreate, SupplierResponse, SupplierUpdate

SUPPLIER_TYPE_LOOKUP_KEY = "SUPPLIER_TYPE"
COUNTRY_LOOKUP_KEY = "COUNTRY"


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ServiceConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _normalize_supplier_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ServiceValidationError("supplier_name is required")
    if len(normalized) > 250:
        raise ServiceValidationError("supplier_name must not exceed 250 characters")
    return normalized


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_lookup_input(value: str, field_name: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    if len(normalized) > 50:
        raise ServiceValidationError(f"{field_name} must not exceed 50 characters")
    return normalized


def _format_allowed_codes(codes: set[str]) -> str:
    return ", ".join(sorted(codes))


async def _get_active_lookup_codes(db: AsyncSession, lookup_key: str) -> set[str]:
    stmt = (
        select(LookupValue.code)
        .join(LookupMaster, LookupValue.lookup_id == LookupMaster.id)
        .where(
            LookupMaster.lookup_key == lookup_key,
            LookupMaster.is_active.is_(True),
            LookupValue.is_active.is_(True),
        )
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def _normalize_lookup_code(
    db: AsyncSession,
    *,
    lookup_key: str,
    value: str,
    field_name: str,
) -> str:
    normalized = _normalize_lookup_input(value, field_name)
    active_codes = await _get_active_lookup_codes(db, lookup_key)
    if not active_codes:
        raise ServiceValidationError(f"{field_name} lookup is not configured")
    if normalized not in active_codes:
        raise ServiceValidationError(f"{field_name} must be one of: {_format_allowed_codes(active_codes)}")
    return normalized


async def _normalize_optional_lookup_code(
    db: AsyncSession,
    *,
    lookup_key: str,
    value: str | None,
    field_name: str,
) -> str | None:
    stripped = _strip_optional(value)
    if stripped is None:
        return None
    return await _normalize_lookup_code(db, lookup_key=lookup_key, value=stripped, field_name=field_name)


def _supplier_query() -> Select[tuple[Supplier]]:
    return select(Supplier)


async def _get_supplier_by_id(db: AsyncSession, supplier_id: uuid.UUID) -> Supplier | None:
    stmt = _supplier_query().where(Supplier.supplier_id == supplier_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_supplier_by_name(db: AsyncSession, supplier_name: str) -> Supplier | None:
    stmt = _supplier_query().where(func.lower(Supplier.supplier_name) == func.lower(supplier_name))
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_suppliers(db: AsyncSession) -> list[SupplierResponse]:
    stmt = _supplier_query().order_by(Supplier.supplier_name.asc())
    result = await db.execute(stmt)
    suppliers = result.scalars().all()
    return [SupplierResponse.model_validate(row) for row in suppliers]


async def get_supplier_by_id(db: AsyncSession, supplier_id: uuid.UUID) -> SupplierResponse:
    supplier = await _get_supplier_by_id(db, supplier_id)
    if supplier is None:
        raise ServiceNotFoundError("Supplier not found")
    return SupplierResponse.model_validate(supplier)


async def create_supplier(db: AsyncSession, payload: SupplierCreate) -> SupplierResponse:
    supplier_name = _normalize_supplier_name(payload.supplier_name)
    supplier_type = await _normalize_lookup_code(
        db,
        lookup_key=SUPPLIER_TYPE_LOOKUP_KEY,
        value=payload.supplier_type,
        field_name="supplier_type",
    )
    supplier_country = await _normalize_optional_lookup_code(
        db,
        lookup_key=COUNTRY_LOOKUP_KEY,
        value=payload.supplier_country,
        field_name="supplier_country",
    )

    duplicate = await _get_supplier_by_name(db, supplier_name)
    if duplicate is not None:
        raise ServiceConflictError("supplier_name already exists")

    now = datetime.now(UTC)
    created_by = _strip_optional(payload.created_by)
    supplier = Supplier(
        supplier_name=supplier_name,
        supplier_type=supplier_type,
        supplier_add1=_strip_optional(payload.supplier_add1),
        supplier_add2=_strip_optional(payload.supplier_add2),
        supplier_city=_strip_optional(payload.supplier_city),
        supplier_pincode=_strip_optional(payload.supplier_pincode),
        supplier_state=_strip_optional(payload.supplier_state),
        supplier_country=supplier_country,
        contact_name=_strip_optional(payload.contact_name),
        contact_email=str(payload.contact_email) if payload.contact_email is not None else None,
        contact_phone=_strip_optional(payload.contact_phone),
        enrolled_dt=now,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(supplier)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to create supplier") from exc

    await db.refresh(supplier)
    return SupplierResponse.model_validate(supplier)


async def update_supplier(db: AsyncSession, supplier_id: uuid.UUID, payload: SupplierUpdate) -> SupplierResponse:
    supplier = await _get_supplier_by_id(db, supplier_id)
    if supplier is None:
        raise ServiceNotFoundError("Supplier not found")

    updates = payload.model_dump(exclude_unset=True)

    if "supplier_name" in updates and updates["supplier_name"] is None:
        raise ServiceValidationError("supplier_name cannot be null")
    if "supplier_type" in updates and updates["supplier_type"] is None:
        raise ServiceValidationError("supplier_type cannot be null")

    if "supplier_name" in updates and updates["supplier_name"] is not None:
        next_name = _normalize_supplier_name(updates["supplier_name"])
        if next_name != supplier.supplier_name:
            duplicate = await _get_supplier_by_name(db, next_name)
            if duplicate is not None and duplicate.supplier_id != supplier.supplier_id:
                raise ServiceConflictError("supplier_name already exists")
        supplier.supplier_name = next_name

    if "supplier_type" in updates and updates["supplier_type"] is not None:
        supplier.supplier_type = await _normalize_lookup_code(
            db,
            lookup_key=SUPPLIER_TYPE_LOOKUP_KEY,
            value=updates["supplier_type"],
            field_name="supplier_type",
        )

    if "supplier_add1" in updates:
        supplier.supplier_add1 = _strip_optional(updates["supplier_add1"])

    if "supplier_add2" in updates:
        supplier.supplier_add2 = _strip_optional(updates["supplier_add2"])

    if "supplier_city" in updates:
        supplier.supplier_city = _strip_optional(updates["supplier_city"])

    if "supplier_pincode" in updates:
        supplier.supplier_pincode = _strip_optional(updates["supplier_pincode"])

    if "supplier_state" in updates:
        supplier.supplier_state = _strip_optional(updates["supplier_state"])

    if "supplier_country" in updates:
        supplier.supplier_country = await _normalize_optional_lookup_code(
            db,
            lookup_key=COUNTRY_LOOKUP_KEY,
            value=updates["supplier_country"],
            field_name="supplier_country",
        )

    if "contact_name" in updates:
        supplier.contact_name = _strip_optional(updates["contact_name"])

    if "contact_email" in updates:
        supplier.contact_email = str(updates["contact_email"]) if updates["contact_email"] is not None else None

    if "contact_phone" in updates:
        supplier.contact_phone = _strip_optional(updates["contact_phone"])

    if "modified_by" in updates:
        supplier.modified_by = _strip_optional(updates["modified_by"])

    supplier.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to update supplier") from exc

    await db.refresh(supplier)
    return SupplierResponse.model_validate(supplier)


async def delete_supplier(db: AsyncSession, supplier_id: uuid.UUID) -> None:
    supplier = await _get_supplier_by_id(db, supplier_id)
    if supplier is None:
        raise ServiceNotFoundError("Supplier not found")

    try:
        await db.delete(supplier)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete supplier") from exc


async def search_supplier(db: AsyncSession, query: str, limit: int = 100) -> list[SupplierResponse]:
    cleaned = query.strip()
    if not cleaned:
        raise ServiceValidationError("Search query must not be empty")

    safe_limit = min(max(limit, 1), 100)
    pattern = f"%{cleaned}%"

    stmt = (
        _supplier_query()
        .where(
            or_(
                Supplier.supplier_name.ilike(pattern),
                Supplier.supplier_type.ilike(pattern),
                Supplier.contact_name.ilike(pattern),
                Supplier.contact_email.ilike(pattern),
                Supplier.contact_phone.ilike(pattern),
                Supplier.supplier_city.ilike(pattern),
            ),
        )
        .order_by(Supplier.supplier_name.asc())
        .limit(safe_limit)
    )
    result = await db.execute(stmt)
    suppliers = result.scalars().all()
    return [SupplierResponse.model_validate(row) for row in suppliers]
