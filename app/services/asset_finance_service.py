import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_finance import AssetFinance
from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.models.supplier import Supplier
from app.schemas.asset_finance_schema import AssetFinanceCreate, AssetFinanceResponse, AssetFinanceUpdate

CURRENCY_LOOKUP_KEY = "CURRENCY"
DEPRECIATION_METHOD_LOOKUP_KEY = "DEPRECIATION_METHOD"
ASSET_CLASS_GL_LOOKUP_KEY = "ASSET_CLASS_GL"
TWO_DECIMAL_PLACES = Decimal("0.01")


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ServiceConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_required(value: str | None, field_name: str, max_len: int) -> str:
    if value is None:
        raise ServiceValidationError(f"{field_name} is required")
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _normalize_optional_string(value: str | None, field_name: str, max_len: int) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _normalize_lookup_input(value: str | None, field_name: str) -> str:
    return _normalize_required(value, field_name, 50).upper()


def _normalize_optional_lookup_input(value: str | None, field_name: str) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if len(normalized) > 50:
        raise ServiceValidationError(f"{field_name} must not exceed 50 characters")
    return normalized


def _normalize_decimal(
    value: Decimal | float | int | str | None,
    field_name: str,
    *,
    required: bool = False,
    positive: bool = False,
    non_negative: bool = False,
    precision: int = 18,
    scale: int = 2,
) -> Decimal | None:
    if value is None:
        if required:
            raise ServiceValidationError(f"{field_name} is required")
        return None

    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ServiceValidationError(f"{field_name} must be a valid decimal number") from exc

    if normalized.is_nan() or normalized.is_infinite():
        raise ServiceValidationError(f"{field_name} must be a valid decimal number")

    quantizer = Decimal("1").scaleb(-scale)
    normalized = normalized.quantize(quantizer, rounding=ROUND_HALF_UP)

    unsigned_text = format(abs(normalized), f".{scale}f")
    integer_part, _, decimal_part = unsigned_text.partition(".")
    if len(integer_part) > precision - scale or len(decimal_part) > scale:
        raise ServiceValidationError(f"{field_name} must fit within {precision} digits and {scale} decimals")

    if positive and normalized <= 0:
        raise ServiceValidationError(f"{field_name} must be greater than 0")
    if non_negative and normalized < 0:
        raise ServiceValidationError(f"{field_name} must be greater than or equal to 0")

    return normalized


def _normalize_url(value: str | None, field_name: str, max_len: int) -> str | None:
    normalized = _normalize_optional_string(value, field_name, max_len)
    if normalized is None:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ServiceValidationError(f"{field_name} must be a valid http or https URL")
    return normalized


def _calculate_book_value(acquisition_cost: Decimal, accumulated_depreciation: Decimal) -> Decimal:
    return (acquisition_cost - accumulated_depreciation).quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


def _calculate_depreciation_rate(useful_life_years: int) -> Decimal:
    return (Decimal("100") / Decimal(useful_life_years)).quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


def _normalize_date_not_future(value: date, field_name: str) -> date:
    today = datetime.now(UTC).date()
    if value > today:
        raise ServiceValidationError(f"{field_name} cannot be later than today")
    return value


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


def _format_allowed_codes(codes: set[str]) -> str:
    return ", ".join(sorted(codes))


async def _normalize_lookup_code(
    db: AsyncSession,
    *,
    lookup_key: str,
    value: str | None,
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
    normalized = _normalize_optional_lookup_input(value, field_name)
    if normalized is None:
        return None
    active_codes = await _get_active_lookup_codes(db, lookup_key)
    if not active_codes:
        raise ServiceValidationError(f"{field_name} lookup is not configured")
    if normalized not in active_codes:
        raise ServiceValidationError(f"{field_name} must be one of: {_format_allowed_codes(active_codes)}")
    return normalized


def _asset_finance_query() -> Select[tuple[AssetFinance]]:
    return select(AssetFinance).options(
        selectinload(AssetFinance.asset),
        selectinload(AssetFinance.supplier),
    )


async def _get_asset_by_uuid(db: AsyncSession, asset_uuid: uuid.UUID) -> Asset | None:
    stmt = select(Asset).where(Asset.asset_uuid == asset_uuid)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_supplier_by_id(db: AsyncSession, supplier_id: uuid.UUID) -> Supplier | None:
    stmt = select(Supplier).where(Supplier.supplier_id == supplier_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_asset_finance_model(db: AsyncSession, asset_uuid: uuid.UUID) -> AssetFinance | None:
    stmt = _asset_finance_query().where(AssetFinance.asset_uuid == asset_uuid)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _validate_asset_reference(db: AsyncSession, asset_uuid: uuid.UUID) -> Asset:
    asset = await _get_asset_by_uuid(db, asset_uuid)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")
    return asset


async def _validate_supplier_reference(db: AsyncSession, supplier_id: uuid.UUID) -> None:
    if await _get_supplier_by_id(db, supplier_id) is None:
        raise ServiceValidationError("supplier_id references an unknown supplier")


async def _normalize_finance_payload(
    db: AsyncSession,
    *,
    acquisition_dt: date,
    purchase_order_no: str | None,
    invoice_ref: str | None,
    supplier_id: uuid.UUID,
    make: str | None,
    model: str | None,
    manufacturer: str | None,
    oem_release_url: str | None,
    capitalization_date: date,
    acquisition_cost: Decimal,
    currency_code: str,
    replacement_value: Decimal | None,
    insured_value: Decimal | None,
    salvage_value: Decimal | None,
    depreciation_method: str,
    useful_life_years: int,
    depreciation_rate_pct: Decimal | None,
    accumulated_depreciation: Decimal,
    cost_center: str | None,
    gl_account_capex: str | None,
    asset_class_gl: str | None,
    wbs_element: str | None,
) -> dict[str, object]:
    acquisition_dt = _normalize_date_not_future(acquisition_dt, "acquisition_dt")
    if capitalization_date < acquisition_dt:
        raise ServiceValidationError("capitalization_date cannot be earlier than acquisition_dt")

    await _validate_supplier_reference(db, supplier_id)

    normalized_acquisition_cost = _normalize_decimal(
        acquisition_cost,
        "acquisition_cost",
        required=True,
        positive=True,
    )
    assert normalized_acquisition_cost is not None

    normalized_accumulated_depreciation = _normalize_decimal(
        accumulated_depreciation,
        "accumulated_depreciation",
        required=True,
        non_negative=True,
    )
    assert normalized_accumulated_depreciation is not None

    if normalized_accumulated_depreciation > normalized_acquisition_cost:
        raise ServiceValidationError("accumulated_depreciation cannot exceed acquisition_cost")

    normalized_depreciation_rate_pct = _normalize_decimal(
        depreciation_rate_pct,
        "depreciation_rate_pct",
        precision=5,
        scale=2,
        non_negative=True,
    )
    if normalized_depreciation_rate_pct is None:
        normalized_depreciation_rate_pct = _calculate_depreciation_rate(useful_life_years)

    book_value = _calculate_book_value(normalized_acquisition_cost, normalized_accumulated_depreciation)
    if book_value < 0:
        raise ServiceValidationError("book_value cannot be negative")

    return {
        "acquisition_dt": acquisition_dt,
        "purchase_order_no": _normalize_optional_string(purchase_order_no, "purchase_order_no", 20),
        "invoice_ref": _normalize_optional_string(invoice_ref, "invoice_ref", 20),
        "supplier_id": supplier_id,
        "make": _normalize_optional_string(make, "make", 50),
        "model": _normalize_optional_string(model, "model", 50),
        "manufacturer": _normalize_optional_string(manufacturer, "manufacturer", 100),
        "oem_release_url": _normalize_url(oem_release_url, "oem_release_url", 500),
        "capitalization_date": capitalization_date,
        "acquisition_cost": normalized_acquisition_cost,
        "currency_code": await _normalize_lookup_code(
            db,
            lookup_key=CURRENCY_LOOKUP_KEY,
            value=currency_code,
            field_name="currency_code",
        ),
        "book_value": book_value,
        "replacement_value": _normalize_decimal(
            replacement_value,
            "replacement_value",
            non_negative=True,
        ),
        "insured_value": _normalize_decimal(
            insured_value,
            "insured_value",
            non_negative=True,
        ),
        "salvage_value": _normalize_decimal(
            salvage_value,
            "salvage_value",
            non_negative=True,
        ),
        "depreciation_method": await _normalize_lookup_code(
            db,
            lookup_key=DEPRECIATION_METHOD_LOOKUP_KEY,
            value=depreciation_method,
            field_name="depreciation_method",
        ),
        "useful_life_years": useful_life_years,
        "depreciation_rate_pct": normalized_depreciation_rate_pct,
        "accumulated_depreciation": normalized_accumulated_depreciation,
        "cost_center": _normalize_optional_string(cost_center, "cost_center", 15),
        "gl_account_capex": _normalize_optional_string(gl_account_capex, "gl_account_capex", 15),
        "asset_class_gl": await _normalize_optional_lookup_code(
            db,
            lookup_key=ASSET_CLASS_GL_LOOKUP_KEY,
            value=asset_class_gl,
            field_name="asset_class_gl",
        ),
        "wbs_element": _normalize_optional_string(wbs_element, "wbs_element", 20),
    }


def _build_asset_finance_response(finance: AssetFinance) -> AssetFinanceResponse:
    asset = finance.asset
    supplier = finance.supplier
    return AssetFinanceResponse(
        finance_id=finance.finance_id,
        asset_uuid=finance.asset_uuid,
        asset_id=asset.asset_id if asset is not None else None,
        asset_name=asset.asset_name if asset is not None else None,
        supplier_id=finance.supplier_id,
        supplier_name=supplier.supplier_name if supplier is not None else None,
        acquisition_dt=finance.acquisition_dt,
        purchase_order_no=finance.purchase_order_no,
        invoice_ref=finance.invoice_ref,
        make=finance.make,
        model=finance.model,
        manufacturer=finance.manufacturer,
        oem_release_url=finance.oem_release_url,
        capitalization_date=finance.capitalization_date,
        acquisition_cost=finance.acquisition_cost,
        currency_code=finance.currency_code,
        book_value=finance.book_value,
        replacement_value=finance.replacement_value,
        insured_value=finance.insured_value,
        salvage_value=finance.salvage_value,
        depreciation_method=finance.depreciation_method,
        useful_life_years=finance.useful_life_years,
        depreciation_rate_pct=finance.depreciation_rate_pct,
        accumulated_depreciation=finance.accumulated_depreciation,
        cost_center=finance.cost_center,
        gl_account_capex=finance.gl_account_capex,
        asset_class_gl=finance.asset_class_gl,
        wbs_element=finance.wbs_element,
        created_by=finance.created_by,
        created_dt=finance.created_dt,
        modified_by=finance.modified_by,
        modified_dt=finance.modified_dt,
    )


def _conflict_message_from_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_asset_finance_asset_uuid" in message or "asset_uuid" in message:
        return "Asset finance already exists for this asset"
    if "chk_asset_finance_book_value_formula" in message:
        return "book_value must equal acquisition_cost minus accumulated_depreciation"
    if "chk_asset_finance_capitalization_not_before_acquisition" in message:
        return "capitalization_date cannot be earlier than acquisition_dt"
    if "chk_asset_finance_useful_life_range" in message:
        return "useful_life_years must be between 1 and 99"
    return "Operation failed due to a data conflict"


async def get_asset_finance_by_asset(db: AsyncSession, asset_uuid: uuid.UUID) -> AssetFinanceResponse | None:
    await _validate_asset_reference(db, asset_uuid)
    finance = await _get_asset_finance_model(db, asset_uuid)
    if finance is None:
        return None
    return _build_asset_finance_response(finance)


async def create_asset_finance(
    db: AsyncSession,
    asset_uuid: uuid.UUID,
    payload: AssetFinanceCreate,
) -> AssetFinanceResponse:
    await _validate_asset_reference(db, asset_uuid)

    duplicate = await _get_asset_finance_model(db, asset_uuid)
    if duplicate is not None:
        raise ServiceConflictError("Asset finance already exists for this asset")

    normalized = await _normalize_finance_payload(
        db,
        acquisition_dt=payload.acquisition_dt,
        purchase_order_no=payload.purchase_order_no,
        invoice_ref=payload.invoice_ref,
        supplier_id=payload.supplier_id,
        make=payload.make,
        model=payload.model,
        manufacturer=payload.manufacturer,
        oem_release_url=payload.oem_release_url,
        capitalization_date=payload.capitalization_date,
        acquisition_cost=payload.acquisition_cost,
        currency_code=payload.currency_code,
        replacement_value=payload.replacement_value,
        insured_value=payload.insured_value,
        salvage_value=payload.salvage_value,
        depreciation_method=payload.depreciation_method,
        useful_life_years=payload.useful_life_years,
        depreciation_rate_pct=payload.depreciation_rate_pct,
        accumulated_depreciation=payload.accumulated_depreciation,
        cost_center=payload.cost_center,
        gl_account_capex=payload.gl_account_capex,
        asset_class_gl=payload.asset_class_gl,
        wbs_element=payload.wbs_element,
    )

    now = datetime.now(UTC)
    created_by = _normalize_required(payload.created_by, "created_by", 150)
    finance = AssetFinance(
        asset_uuid=asset_uuid,
        **normalized,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(finance)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_asset_finance_by_asset(db, asset_uuid)


async def update_asset_finance(
    db: AsyncSession,
    asset_uuid: uuid.UUID,
    payload: AssetFinanceUpdate,
) -> AssetFinanceResponse:
    finance = await _get_asset_finance_model(db, asset_uuid)
    if finance is None:
        if await _get_asset_by_uuid(db, asset_uuid) is None:
            raise ServiceNotFoundError("Asset not found")
        raise ServiceNotFoundError("Asset finance not found")

    updates = payload.model_dump(exclude_unset=True)

    required_fields = (
        "acquisition_dt",
        "supplier_id",
        "capitalization_date",
        "acquisition_cost",
        "currency_code",
        "depreciation_method",
        "useful_life_years",
        "accumulated_depreciation",
    )
    for field_name in required_fields:
        if field_name in updates and updates[field_name] is None:
            raise ServiceValidationError(f"{field_name} cannot be null")

    next_useful_life_years = updates.get("useful_life_years", finance.useful_life_years)
    next_depreciation_rate_pct = finance.depreciation_rate_pct
    if "depreciation_rate_pct" in updates:
        next_depreciation_rate_pct = updates["depreciation_rate_pct"]
    elif "useful_life_years" in updates:
        existing_auto_rate = _calculate_depreciation_rate(finance.useful_life_years)
        if finance.depreciation_rate_pct == existing_auto_rate:
            next_depreciation_rate_pct = _calculate_depreciation_rate(next_useful_life_years)

    normalized = await _normalize_finance_payload(
        db,
        acquisition_dt=updates.get("acquisition_dt", finance.acquisition_dt),
        purchase_order_no=updates.get("purchase_order_no", finance.purchase_order_no),
        invoice_ref=updates.get("invoice_ref", finance.invoice_ref),
        supplier_id=updates.get("supplier_id", finance.supplier_id),
        make=updates.get("make", finance.make),
        model=updates.get("model", finance.model),
        manufacturer=updates.get("manufacturer", finance.manufacturer),
        oem_release_url=updates.get("oem_release_url", finance.oem_release_url),
        capitalization_date=updates.get("capitalization_date", finance.capitalization_date),
        acquisition_cost=updates.get("acquisition_cost", finance.acquisition_cost),
        currency_code=updates.get("currency_code", finance.currency_code),
        replacement_value=updates.get("replacement_value", finance.replacement_value),
        insured_value=updates.get("insured_value", finance.insured_value),
        salvage_value=updates.get("salvage_value", finance.salvage_value),
        depreciation_method=updates.get("depreciation_method", finance.depreciation_method),
        useful_life_years=next_useful_life_years,
        depreciation_rate_pct=next_depreciation_rate_pct,
        accumulated_depreciation=updates.get("accumulated_depreciation", finance.accumulated_depreciation),
        cost_center=updates.get("cost_center", finance.cost_center),
        gl_account_capex=updates.get("gl_account_capex", finance.gl_account_capex),
        asset_class_gl=updates.get("asset_class_gl", finance.asset_class_gl),
        wbs_element=updates.get("wbs_element", finance.wbs_element),
    )

    for field_name, field_value in normalized.items():
        setattr(finance, field_name, field_value)

    if "modified_by" in updates:
        finance.modified_by = _normalize_optional_string(updates["modified_by"], "modified_by", 150)
    finance.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_asset_finance_by_asset(db, asset_uuid)


async def delete_asset_finance(db: AsyncSession, asset_uuid: uuid.UUID) -> None:
    finance = await _get_asset_finance_model(db, asset_uuid)
    if finance is None:
        if await _get_asset_by_uuid(db, asset_uuid) is None:
            raise ServiceNotFoundError("Asset not found")
        raise ServiceNotFoundError("Asset finance not found")

    try:
        await db.delete(finance)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete asset finance") from exc
