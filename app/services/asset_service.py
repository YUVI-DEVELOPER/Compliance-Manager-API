import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, String, cast, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_spec import AssetSpec
from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.models.org_structure import OrgStructure
from app.models.supplier import Supplier
from app.schemas.asset_schema import AssetCreate, AssetResponse, AssetSpecValue, AssetUpdate

ASSET_CLASS_LOOKUP_KEY = "ASSET_CLASS"
ASSET_CATEGORY_LOOKUP_KEY = "ASSET_CATEGORY"
ASSET_SUB_CATEGORY_LOOKUP_KEY = "ASSET_SUB_CATEGORY"
ASSET_TYPE_LOOKUP_KEY = "ASSET_TYPE"
CRITICALITY_CLASS_LOOKUP_KEY = "CRITICALITY_CLASS"
LEGACY_CRITICALITY_LOOKUP_KEY = "ASSET_CRITICALITY"
ASSET_NATURE_LOOKUP_KEY = "ASSET_NATURE"
ASSET_STATUS_LOOKUP_KEY = "ASSET_STATUS"
CURRENCY_LOOKUP_KEY = "CURRENCY"
UPGRADE_SUPPORTED_METADATA_KEY = "is_upgrade_supported"


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
    normalized = _normalize_required(value, field_name, 50).upper()
    return normalized


def _normalize_optional_lookup_input(value: str | None, field_name: str) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if len(normalized) > 50:
        raise ServiceValidationError(f"{field_name} must not exceed 50 characters")
    return normalized


def _normalize_tags(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None

    normalized_tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in value:
        normalized = str(raw_tag).strip()
        if not normalized:
            continue
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_tags.append(normalized)

    return normalized_tags or None


def _normalize_asset_spec_values_for_response(
    value: object,
) -> list[dict[str, str | None]] | None:
    if not isinstance(value, list):
        return None

    normalized_items: list[dict[str, str | None]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            continue

        asset_spec_id = _strip_optional(str(raw_item.get("asset_spec_id") or ""))
        parameter_grouping = _strip_optional(str(raw_item.get("parameter_grouping") or ""))
        parameter_name = _strip_optional(str(raw_item.get("parameter_name") or ""))
        parameter_value = _strip_optional(str(raw_item.get("parameter_value") or ""))

        if not asset_spec_id or not parameter_grouping or not parameter_name or parameter_value is None:
            continue

        parameter_description_raw = raw_item.get("parameter_description")
        if parameter_description_raw is None and "guidelines" in raw_item:
            parameter_description_raw = raw_item.get("guidelines")

        normalized_items.append(
            {
                "asset_spec_id": asset_spec_id,
                "parameter_grouping": parameter_grouping,
                "parameter_name": parameter_name,
                "parameter_description": _strip_optional(
                    None if parameter_description_raw is None else str(parameter_description_raw)
                ),
                "parameter_value": parameter_value,
            }
        )

    return normalized_items or None


def _format_allowed_codes(codes: set[str]) -> str:
    return ", ".join(sorted(codes))


def _is_lookup_metadata_truthy(metadata: dict | None, key: str) -> bool:
    if not metadata:
        return False
    raw_value = metadata.get(key)
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return bool(raw_value)
    if isinstance(raw_value, str):
        return raw_value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return False


async def _get_active_lookup_values(
    db: AsyncSession,
    lookup_key: str,
    *,
    codes: set[str] | None = None,
) -> dict[str, LookupValue]:
    stmt = (
        select(LookupValue)
        .join(LookupMaster, LookupValue.lookup_id == LookupMaster.id)
        .where(
            LookupMaster.lookup_key == lookup_key,
            LookupMaster.is_active.is_(True),
            LookupValue.is_active.is_(True),
        )
        .order_by(LookupValue.sort_order.asc(), LookupValue.code.asc())
    )
    if codes:
        stmt = stmt.where(LookupValue.code.in_(codes))

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {row.code: row for row in rows}


async def _get_active_lookup_codes(db: AsyncSession, lookup_key: str) -> set[str]:
    return set((await _get_active_lookup_values(db, lookup_key)).keys())


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


async def _normalize_lookup_code_with_fallback(
    db: AsyncSession,
    *,
    lookup_keys: tuple[str, ...],
    value: str | None,
    field_name: str,
) -> str:
    normalized = _normalize_lookup_input(value, field_name)

    configured_codes: set[str] = set()
    for lookup_key in lookup_keys:
        active_codes = await _get_active_lookup_codes(db, lookup_key)
        if normalized in active_codes:
            return normalized
        configured_codes.update(active_codes)

    if not configured_codes:
        raise ServiceValidationError(f"{field_name} lookup is not configured")
    raise ServiceValidationError(f"{field_name} must be one of: {_format_allowed_codes(configured_codes)}")


def _asset_query() -> Select[tuple[Asset]]:
    return select(Asset).options(selectinload(Asset.org_node), selectinload(Asset.supplier))


async def _get_asset_by_uuid(db: AsyncSession, asset_uuid: uuid.UUID) -> Asset | None:
    stmt = _asset_query().where(Asset.asset_uuid == asset_uuid)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_asset_by_business_id(db: AsyncSession, business_asset_id: str) -> Asset | None:
    stmt = _asset_query().where(Asset.asset_id == business_asset_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_asset_by_serial(db: AsyncSession, serial_number: str) -> Asset | None:
    stmt = _asset_query().where(Asset.serial_number == serial_number)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_active_org_node(db: AsyncSession, org_node_id: uuid.UUID) -> OrgStructure | None:
    stmt = select(OrgStructure).where(
        OrgStructure.id == org_node_id,
        OrgStructure.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_supplier_by_id(db: AsyncSession, supplier_id: uuid.UUID) -> Supplier | None:
    stmt = select(Supplier).where(Supplier.supplier_id == supplier_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _validate_org_node_id(db: AsyncSession, org_node_id: uuid.UUID) -> None:
    if await _get_active_org_node(db, org_node_id) is None:
        raise ServiceValidationError("org_node_id references an unknown or deleted org node")


async def _validate_supplier_id(db: AsyncSession, supplier_id: uuid.UUID | None) -> None:
    if supplier_id is None:
        return
    if await _get_supplier_by_id(db, supplier_id) is None:
        raise ServiceValidationError("supplier_id references an unknown supplier")


async def _get_active_asset_specs_for_sub_category(
    db: AsyncSession,
    asset_sub_category_code: str,
) -> list[AssetSpec]:
    lookup_values = await _get_active_lookup_values(
        db,
        ASSET_SUB_CATEGORY_LOOKUP_KEY,
        codes={asset_sub_category_code},
    )
    sub_category = lookup_values.get(asset_sub_category_code)
    if sub_category is None:
        raise ServiceValidationError("asset_sub_category references an unknown or inactive lookup value")

    stmt = (
        select(AssetSpec)
        .where(
            AssetSpec.asset_sub_category_id == sub_category.id,
            AssetSpec.is_active.is_(True),
        )
        .order_by(AssetSpec.parameter_grouping.asc(), AssetSpec.parameter_seq.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def _resolve_asset_spec_values(
    db: AsyncSession,
    *,
    asset_sub_category_code: str,
    submitted_values: list[AssetSpecValue] | list[dict[str, str | None]] | None,
) -> list[dict[str, str | None]] | None:
    specs = await _get_active_asset_specs_for_sub_category(db, asset_sub_category_code)
    if not specs:
        return None

    overrides_by_id: dict[str, dict[str, str | None]] = {}
    overrides_by_key: dict[tuple[str, str], dict[str, str | None]] = {}
    for raw_item in submitted_values or []:
        item = raw_item.model_dump() if isinstance(raw_item, AssetSpecValue) else raw_item
        asset_spec_id = _strip_optional(str(item.get("asset_spec_id") or ""))
        if asset_spec_id:
            overrides_by_id[asset_spec_id] = item

        grouping = _strip_optional(str(item.get("parameter_grouping") or ""))
        name = _strip_optional(str(item.get("parameter_name") or ""))
        if grouping and name:
            overrides_by_key[(grouping.lower(), name.lower())] = item

    resolved_values: list[dict[str, str | None]] = []
    for spec in specs:
        override = overrides_by_id.get(str(spec.asset_spec_id)) or overrides_by_key.get(
            (spec.parameter_grouping.lower(), spec.parameter_name.lower())
        )
        parameter_value = spec.parameter_value
        if override is not None:
            override_value = override.get("parameter_value")
            if override_value is not None:
                parameter_value = _normalize_required(str(override_value), "asset_spec_values.parameter_value", 150)

        resolved_values.append(
            {
                "asset_spec_id": str(spec.asset_spec_id),
                "parameter_grouping": spec.parameter_grouping,
                "parameter_name": spec.parameter_name,
                "parameter_description": spec.guidelines,
                "parameter_value": parameter_value,
            }
        )

    return resolved_values


async def _get_asset_class_upgrade_support_map(
    db: AsyncSession,
    class_codes: set[str],
) -> dict[str, bool]:
    if not class_codes:
        return {}

    lookup_values = await _get_active_lookup_values(db, ASSET_CLASS_LOOKUP_KEY, codes=class_codes)
    return {
        code: _is_lookup_metadata_truthy(lookup_value.metadata_json, UPGRADE_SUPPORTED_METADATA_KEY)
        for code, lookup_value in lookup_values.items()
    }


async def is_asset_class_upgrade_supported(db: AsyncSession, asset_class: str | None) -> bool:
    normalized = _normalize_optional_lookup_input(asset_class, "asset_class")
    if normalized is None:
        return False
    support_map = await _get_asset_class_upgrade_support_map(db, {normalized})
    return support_map.get(normalized, False)


def _build_asset_response(asset: Asset, *, asset_class_upgrade_supported: bool) -> AssetResponse:
    org_node = asset.org_node
    supplier = asset.supplier

    return AssetResponse(
        asset_uuid=asset.asset_uuid,
        asset_id=asset.asset_id,
        org_node_id=asset.org_node_id,
        org_node_name=org_node.name if org_node is not None else None,
        supplier_id=asset.supplier_id,
        supplier_name=supplier.supplier_name if supplier is not None else None,
        legacy_id=asset.legacy_id,
        qr_barcode=asset.qr_barcode,
        rfid_tag=asset.rfid_tag,
        serial_number=asset.serial_number,
        asset_class=asset.asset_class,
        asset_category=asset.asset_category,
        asset_sub_category=asset.asset_sub_category,
        asset_type=asset.asset_type,
        criticality_class=asset.criticality_class,
        asset_nature=asset.asset_nature,
        tags=asset.tags,
        asset_name=asset.asset_name,
        asset_description=asset.asset_description,
        short_description=asset.short_description,
        tag_number=asset.tag_number,
        asset_owner=asset.asset_owner,
        manufacturer=asset.manufacturer,
        model=asset.model,
        asset_version=asset.asset_version,
        asset_commission_dt=asset.asset_commission_dt,
        asset_purchase_dt=asset.asset_purchase_dt,
        asset_purchase_ref=asset.asset_purchase_ref,
        warranty_period=asset.warranty_period,
        asset_value=asset.asset_value,
        asset_currency=asset.asset_currency,
        asset_release_url=asset.asset_release_url,
        asset_status=asset.asset_status,
        asset_spec_values=_normalize_asset_spec_values_for_response(asset.asset_spec_values),
        can_create_release=asset_class_upgrade_supported,
        asset_class_upgrade_supported=asset_class_upgrade_supported,
        created_by=asset.created_by,
        created_dt=asset.created_dt,
        modified_by=asset.modified_by,
        modified_dt=asset.modified_dt,
        asset_code=asset.asset_id,
        asset_serial_no=asset.serial_number,
        asset_criticality=asset.criticality_class,
    )


async def _build_asset_responses(db: AsyncSession, assets: list[Asset]) -> list[AssetResponse]:
    support_map = await _get_asset_class_upgrade_support_map(
        db,
        {asset.asset_class for asset in assets if asset.asset_class},
    )
    return [
        _build_asset_response(
            asset,
            asset_class_upgrade_supported=support_map.get(asset.asset_class, False),
        )
        for asset in assets
    ]


def _conflict_message_from_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "asset_code" in message and "unique" in message:
        return "asset_id already exists"
    if "asset_serial_no" in message and "unique" in message:
        return "serial_number already exists"
    return "Operation failed due to a data conflict"


async def get_assets(
    db: AsyncSession,
    org_node_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
) -> list[AssetResponse]:
    stmt = _asset_query()

    if org_node_id is not None:
        stmt = stmt.where(Asset.org_node_id == org_node_id)

    if supplier_id is not None:
        stmt = stmt.where(Asset.supplier_id == supplier_id)

    stmt = stmt.order_by(Asset.asset_name.asc(), Asset.asset_id.asc())

    result = await db.execute(stmt)
    assets = result.scalars().all()
    return await _build_asset_responses(db, assets)


async def get_asset_by_id(db: AsyncSession, asset_id: uuid.UUID) -> AssetResponse:
    asset = await _get_asset_by_uuid(db, asset_id)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")

    return _build_asset_response(
        asset,
        asset_class_upgrade_supported=await is_asset_class_upgrade_supported(db, asset.asset_class),
    )


async def create_asset(db: AsyncSession, payload: AssetCreate) -> AssetResponse:
    await _validate_org_node_id(db, payload.org_node_id)
    await _validate_supplier_id(db, payload.supplier_id)

    business_asset_id = _normalize_required(payload.asset_id, "asset_id", 20)
    serial_number = _normalize_optional_string(payload.serial_number, "serial_number", 50)

    duplicate = await _get_asset_by_business_id(db, business_asset_id)
    if duplicate is not None:
        raise ServiceConflictError("asset_id already exists")

    if serial_number is not None:
        duplicate = await _get_asset_by_serial(db, serial_number)
        if duplicate is not None:
            raise ServiceConflictError("serial_number already exists")

    asset_class = await _normalize_lookup_code(
        db,
        lookup_key=ASSET_CLASS_LOOKUP_KEY,
        value=payload.asset_class,
        field_name="asset_class",
    )
    asset_category = await _normalize_lookup_code(
        db,
        lookup_key=ASSET_CATEGORY_LOOKUP_KEY,
        value=payload.asset_category,
        field_name="asset_category",
    )
    asset_sub_category = await _normalize_lookup_code(
        db,
        lookup_key=ASSET_SUB_CATEGORY_LOOKUP_KEY,
        value=payload.asset_sub_category,
        field_name="asset_sub_category",
    )
    asset_type = await _normalize_optional_lookup_code(
        db,
        lookup_key=ASSET_TYPE_LOOKUP_KEY,
        value=payload.asset_type,
        field_name="asset_type",
    )
    criticality_class = await _normalize_lookup_code_with_fallback(
        db,
        lookup_keys=(CRITICALITY_CLASS_LOOKUP_KEY, LEGACY_CRITICALITY_LOOKUP_KEY),
        value=payload.criticality_class,
        field_name="criticality_class",
    )
    asset_nature = await _normalize_lookup_code(
        db,
        lookup_key=ASSET_NATURE_LOOKUP_KEY,
        value=payload.asset_nature,
        field_name="asset_nature",
    )
    asset_currency = await _normalize_optional_lookup_code(
        db,
        lookup_key=CURRENCY_LOOKUP_KEY,
        value=payload.asset_currency,
        field_name="asset_currency",
    )
    asset_status = await _normalize_optional_lookup_code(
        db,
        lookup_key=ASSET_STATUS_LOOKUP_KEY,
        value=payload.asset_status,
        field_name="asset_status",
    )
    asset_spec_values = await _resolve_asset_spec_values(
        db,
        asset_sub_category_code=asset_sub_category,
        submitted_values=payload.asset_spec_values,
    )

    now = datetime.now(UTC)
    created_by = _normalize_required(payload.created_by, "created_by", 150)
    asset = Asset(
        org_node_id=payload.org_node_id,
        asset_id=business_asset_id,
        legacy_id=_normalize_optional_string(payload.legacy_id, "legacy_id", 30),
        qr_barcode=_normalize_optional_string(payload.qr_barcode, "qr_barcode", 50),
        rfid_tag=_normalize_optional_string(payload.rfid_tag, "rfid_tag", 30),
        serial_number=serial_number,
        asset_class=asset_class,
        asset_category=asset_category,
        asset_sub_category=asset_sub_category,
        asset_type=asset_type,
        criticality_class=criticality_class,
        asset_nature=asset_nature,
        tags=_normalize_tags(payload.tags),
        asset_name=_normalize_required(payload.asset_name, "asset_name", 100),
        asset_description=_normalize_required(payload.asset_description, "asset_description", 500),
        short_description=_normalize_required(payload.short_description, "short_description", 40),
        tag_number=_normalize_optional_string(payload.tag_number, "tag_number", 20),
        asset_owner=_normalize_required(payload.asset_owner, "asset_owner", 150),
        supplier_id=payload.supplier_id,
        manufacturer=_normalize_optional_string(payload.manufacturer, "manufacturer", 200),
        model=_normalize_optional_string(payload.model, "model", 100),
        asset_version=_normalize_optional_string(payload.asset_version, "asset_version", 25),
        asset_commission_dt=payload.asset_commission_dt,
        asset_purchase_dt=payload.asset_purchase_dt,
        asset_purchase_ref=_normalize_optional_string(payload.asset_purchase_ref, "asset_purchase_ref", 50),
        warranty_period=payload.warranty_period,
        asset_value=payload.asset_value,
        asset_currency=asset_currency,
        asset_release_url=_normalize_optional_string(payload.asset_release_url, "asset_release_url", 250),
        asset_status=asset_status,
        asset_spec_values=asset_spec_values,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(asset)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    await db.refresh(asset)
    return await get_asset_by_id(db, asset.asset_uuid)


async def update_asset(db: AsyncSession, asset_id: uuid.UUID, payload: AssetUpdate) -> AssetResponse:
    asset = await _get_asset_by_uuid(db, asset_id)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")

    updates = payload.model_dump(exclude_unset=True)

    required_nullable_fields = (
        "org_node_id",
        "asset_id",
        "asset_class",
        "asset_category",
        "asset_sub_category",
        "criticality_class",
        "asset_nature",
        "asset_name",
        "asset_description",
        "short_description",
        "asset_owner",
    )
    for field_name in required_nullable_fields:
        if field_name in updates and updates[field_name] is None:
            raise ServiceValidationError(f"{field_name} cannot be null")

    if "org_node_id" in updates and updates["org_node_id"] is not None:
        await _validate_org_node_id(db, updates["org_node_id"])
        asset.org_node_id = updates["org_node_id"]

    if "supplier_id" in updates:
        await _validate_supplier_id(db, updates["supplier_id"])
        asset.supplier_id = updates["supplier_id"]

    if "asset_id" in updates:
        next_asset_id = _normalize_required(updates["asset_id"], "asset_id", 20)
        if next_asset_id != asset.asset_id:
            duplicate = await _get_asset_by_business_id(db, next_asset_id)
            if duplicate is not None and duplicate.asset_uuid != asset.asset_uuid:
                raise ServiceConflictError("asset_id already exists")
        asset.asset_id = next_asset_id

    if "serial_number" in updates:
        next_serial_number = _normalize_optional_string(updates["serial_number"], "serial_number", 50)
        if next_serial_number is not None and next_serial_number != asset.serial_number:
            duplicate = await _get_asset_by_serial(db, next_serial_number)
            if duplicate is not None and duplicate.asset_uuid != asset.asset_uuid:
                raise ServiceConflictError("serial_number already exists")
        asset.serial_number = next_serial_number

    if "legacy_id" in updates:
        asset.legacy_id = _normalize_optional_string(updates["legacy_id"], "legacy_id", 30)

    if "qr_barcode" in updates:
        asset.qr_barcode = _normalize_optional_string(updates["qr_barcode"], "qr_barcode", 50)

    if "rfid_tag" in updates:
        asset.rfid_tag = _normalize_optional_string(updates["rfid_tag"], "rfid_tag", 30)

    if "asset_class" in updates:
        asset.asset_class = await _normalize_lookup_code(
            db,
            lookup_key=ASSET_CLASS_LOOKUP_KEY,
            value=updates["asset_class"],
            field_name="asset_class",
        )

    if "asset_category" in updates:
        asset.asset_category = await _normalize_lookup_code(
            db,
            lookup_key=ASSET_CATEGORY_LOOKUP_KEY,
            value=updates["asset_category"],
            field_name="asset_category",
        )

    if "asset_sub_category" in updates:
        asset.asset_sub_category = await _normalize_lookup_code(
            db,
            lookup_key=ASSET_SUB_CATEGORY_LOOKUP_KEY,
            value=updates["asset_sub_category"],
            field_name="asset_sub_category",
        )

    if "asset_type" in updates:
        asset.asset_type = await _normalize_optional_lookup_code(
            db,
            lookup_key=ASSET_TYPE_LOOKUP_KEY,
            value=updates["asset_type"],
            field_name="asset_type",
        )

    if "criticality_class" in updates:
        asset.criticality_class = await _normalize_lookup_code_with_fallback(
            db,
            lookup_keys=(CRITICALITY_CLASS_LOOKUP_KEY, LEGACY_CRITICALITY_LOOKUP_KEY),
            value=updates["criticality_class"],
            field_name="criticality_class",
        )

    if "asset_nature" in updates:
        asset.asset_nature = await _normalize_lookup_code(
            db,
            lookup_key=ASSET_NATURE_LOOKUP_KEY,
            value=updates["asset_nature"],
            field_name="asset_nature",
        )

    if "tags" in updates:
        asset.tags = _normalize_tags(updates["tags"])

    if "asset_name" in updates:
        asset.asset_name = _normalize_required(updates["asset_name"], "asset_name", 100)

    if "asset_description" in updates:
        asset.asset_description = _normalize_required(updates["asset_description"], "asset_description", 500)

    if "short_description" in updates:
        asset.short_description = _normalize_required(updates["short_description"], "short_description", 40)

    if "tag_number" in updates:
        asset.tag_number = _normalize_optional_string(updates["tag_number"], "tag_number", 20)

    if "asset_owner" in updates:
        asset.asset_owner = _normalize_required(updates["asset_owner"], "asset_owner", 150)

    if "manufacturer" in updates:
        asset.manufacturer = _normalize_optional_string(updates["manufacturer"], "manufacturer", 200)

    if "model" in updates:
        asset.model = _normalize_optional_string(updates["model"], "model", 100)

    if "asset_version" in updates:
        asset.asset_version = _normalize_optional_string(updates["asset_version"], "asset_version", 25)

    if "asset_commission_dt" in updates:
        asset.asset_commission_dt = updates["asset_commission_dt"]

    if "asset_purchase_dt" in updates:
        asset.asset_purchase_dt = updates["asset_purchase_dt"]

    if "asset_purchase_ref" in updates:
        asset.asset_purchase_ref = _normalize_optional_string(updates["asset_purchase_ref"], "asset_purchase_ref", 50)

    if "warranty_period" in updates:
        asset.warranty_period = updates["warranty_period"]

    if "asset_value" in updates:
        asset.asset_value = updates["asset_value"]

    if "asset_currency" in updates:
        asset.asset_currency = await _normalize_optional_lookup_code(
            db,
            lookup_key=CURRENCY_LOOKUP_KEY,
            value=updates["asset_currency"],
            field_name="asset_currency",
        )

    if "asset_release_url" in updates:
        asset.asset_release_url = _normalize_optional_string(updates["asset_release_url"], "asset_release_url", 250)

    if "asset_status" in updates:
        asset.asset_status = await _normalize_optional_lookup_code(
            db,
            lookup_key=ASSET_STATUS_LOOKUP_KEY,
            value=updates["asset_status"],
            field_name="asset_status",
        )

    if "asset_sub_category" in updates or "asset_spec_values" in updates:
        asset.asset_spec_values = await _resolve_asset_spec_values(
            db,
            asset_sub_category_code=asset.asset_sub_category,
            submitted_values=updates.get("asset_spec_values"),
        )

    if "modified_by" in updates:
        asset.modified_by = _normalize_optional_string(updates["modified_by"], "modified_by", 150)

    asset.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    await db.refresh(asset)
    return await get_asset_by_id(db, asset.asset_uuid)


async def delete_asset(db: AsyncSession, asset_id: uuid.UUID) -> None:
    asset = await _get_asset_by_uuid(db, asset_id)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")

    try:
        await db.delete(asset)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete asset") from exc


async def search_asset(db: AsyncSession, query: str, limit: int = 100) -> list[AssetResponse]:
    cleaned = query.strip()
    if not cleaned:
        raise ServiceValidationError("Search query must not be empty")

    safe_limit = min(max(limit, 1), 100)
    pattern = f"%{cleaned}%"

    stmt = (
        _asset_query()
        .where(
            or_(
                Asset.asset_id.ilike(pattern),
                Asset.asset_name.ilike(pattern),
                Asset.asset_description.ilike(pattern),
                Asset.short_description.ilike(pattern),
                Asset.serial_number.ilike(pattern),
                Asset.legacy_id.ilike(pattern),
                Asset.qr_barcode.ilike(pattern),
                Asset.rfid_tag.ilike(pattern),
                Asset.tag_number.ilike(pattern),
                Asset.asset_owner.ilike(pattern),
                Asset.manufacturer.ilike(pattern),
                Asset.model.ilike(pattern),
                cast(Asset.tags, String).ilike(pattern),
            )
        )
        .order_by(Asset.asset_name.asc(), Asset.asset_id.asc())
        .limit(safe_limit)
    )
    result = await db.execute(stmt)
    assets = result.scalars().all()
    return await _build_asset_responses(db, assets)
