import uuid
from collections import defaultdict
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.org_structure import OrgStructure
from app.models.supplier import Supplier
from app.schemas.asset_schema import AssetInventoryReportResponse, AssetInventoryReportRow

ReportScope = Literal["enterprise", "unit"]


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_filter_code(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    return normalized.upper() if normalized is not None else None


async def _get_visible_org_nodes(db: AsyncSession) -> list[OrgStructure]:
    stmt = select(OrgStructure).where(OrgStructure.is_deleted.is_(False))
    result = await db.execute(stmt)
    return result.scalars().all()


def _collect_scope_org_ids(org_rows: list[OrgStructure], root_id: uuid.UUID) -> set[uuid.UUID]:
    children_by_parent: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    visible_org_ids = {row.id for row in org_rows}

    for row in org_rows:
        children_by_parent[row.parent_id].append(row.id)

    if root_id not in visible_org_ids:
        raise ServiceNotFoundError("Selected organization scope was not found")

    scoped_ids: set[uuid.UUID] = set()
    stack = [root_id]
    while stack:
        current_id = stack.pop()
        if current_id in scoped_ids:
            continue
        scoped_ids.add(current_id)
        stack.extend(children_by_parent.get(current_id, []))

    return scoped_ids


def _build_report_row(asset: Asset) -> AssetInventoryReportRow:
    org_node = asset.org_node
    supplier = asset.supplier

    return AssetInventoryReportRow(
        asset_uuid=asset.asset_uuid,
        asset_id=asset.asset_id,
        asset_name=asset.asset_name,
        asset_class=asset.asset_class,
        asset_category=asset.asset_category,
        asset_sub_category=asset.asset_sub_category,
        asset_type=asset.asset_type,
        org_node_id=asset.org_node_id,
        org_node_name=org_node.name if org_node is not None else None,
        org_node_code=org_node.code if org_node is not None else None,
        supplier_id=asset.supplier_id,
        supplier_name=supplier.supplier_name if supplier is not None else None,
        asset_owner=asset.asset_owner,
        criticality_class=asset.criticality_class,
        lifecycle_state=asset.asset_status,
        asset_status=asset.asset_status,
        serial_number=asset.serial_number,
        tag_number=asset.tag_number,
        legacy_id=asset.legacy_id,
        manufacturer=asset.manufacturer,
        model=asset.model,
        asset_commission_dt=asset.asset_commission_dt,
        asset_purchase_dt=asset.asset_purchase_dt,
    )


async def get_asset_inventory_report(
    db: AsyncSession,
    *,
    scope: ReportScope = "enterprise",
    org_id: uuid.UUID | None = None,
    q: str | None = None,
    lifecycle_state: str | None = None,
    asset_class: str | None = None,
    asset_category: str | None = None,
) -> AssetInventoryReportResponse:
    if scope == "unit" and org_id is None:
        raise ServiceValidationError("org_id is required when scope is unit")

    visible_org_rows = await _get_visible_org_nodes(db)
    visible_org_map = {row.id: row for row in visible_org_rows}

    scoped_org_ids: set[uuid.UUID] | None = None
    scoped_org_name: str | None = None
    includes_descendants = False

    if scope == "unit" and org_id is not None:
        scoped_org_ids = _collect_scope_org_ids(visible_org_rows, org_id)
        scoped_org = visible_org_map[org_id]
        scoped_org_name = scoped_org.name
        includes_descendants = True

    stmt = (
        select(Asset)
        .join(OrgStructure, Asset.org_node_id == OrgStructure.id)
        .outerjoin(Supplier, Asset.supplier_id == Supplier.supplier_id)
        .options(selectinload(Asset.org_node), selectinload(Asset.supplier))
        .where(OrgStructure.is_deleted.is_(False))
    )

    if scoped_org_ids is not None:
        stmt = stmt.where(Asset.org_node_id.in_(scoped_org_ids))

    normalized_lifecycle_state = _normalize_filter_code(lifecycle_state)
    if normalized_lifecycle_state is not None:
        stmt = stmt.where(Asset.asset_status == normalized_lifecycle_state)

    normalized_asset_class = _normalize_filter_code(asset_class)
    if normalized_asset_class is not None:
        stmt = stmt.where(Asset.asset_class == normalized_asset_class)

    normalized_asset_category = _normalize_filter_code(asset_category)
    if normalized_asset_category is not None:
        stmt = stmt.where(Asset.asset_category == normalized_asset_category)

    cleaned_query = _strip_optional(q)
    if cleaned_query is not None:
        pattern = f"%{cleaned_query}%"
        stmt = stmt.where(
            or_(
                Asset.asset_id.ilike(pattern),
                Asset.asset_name.ilike(pattern),
                Asset.short_description.ilike(pattern),
                Asset.serial_number.ilike(pattern),
                Asset.tag_number.ilike(pattern),
                Asset.legacy_id.ilike(pattern),
                Asset.asset_owner.ilike(pattern),
                Asset.manufacturer.ilike(pattern),
                Asset.model.ilike(pattern),
                cast(Asset.tags, String).ilike(pattern),
                OrgStructure.name.ilike(pattern),
                OrgStructure.code.ilike(pattern),
                Supplier.supplier_name.ilike(pattern),
            ),
        )

    stmt = stmt.order_by(OrgStructure.name.asc(), Asset.asset_name.asc(), Asset.asset_id.asc())

    result = await db.execute(stmt)
    assets = result.scalars().all()
    items = [_build_report_row(asset) for asset in assets]

    return AssetInventoryReportResponse(
        scope=scope,
        org_id=org_id if scope == "unit" else None,
        org_name=scoped_org_name,
        includes_descendants=includes_descendants,
        total=len(items),
        items=items,
    )
