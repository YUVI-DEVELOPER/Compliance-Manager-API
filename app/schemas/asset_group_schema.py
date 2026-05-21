import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


AssetGroupType = Literal["SYSTEM", "SUB_SYSTEM"]


class AssetGroupCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    group_name: str = Field(..., min_length=1, max_length=150)
    group_type: AssetGroupType
    created_by: str = Field(..., min_length=1, max_length=150, validation_alias=AliasChoices("created_by", "createdBy"))
    group_code: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("group_code", "groupCode"),
    )
    description: str | None = Field(default=None, max_length=500)
    parent_group_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("parent_group_id", "parentGroupId"),
    )
    org_node_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("org_node_id", "orgNodeId"),
    )
    is_active: bool = Field(default=True, validation_alias=AliasChoices("is_active", "isActive"))


class AssetGroupUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    group_name: str | None = Field(default=None, min_length=1, max_length=150)
    group_type: AssetGroupType | None = None
    group_code: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("group_code", "groupCode"),
    )
    description: str | None = Field(default=None, max_length=500)
    parent_group_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("parent_group_id", "parentGroupId"),
    )
    org_node_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("org_node_id", "orgNodeId"),
    )
    is_active: bool | None = Field(default=None, validation_alias=AliasChoices("is_active", "isActive"))
    modified_by: str | None = Field(
        default=None,
        max_length=150,
        validation_alias=AliasChoices("modified_by", "modifiedBy"),
    )


class AssetGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_group_id: uuid.UUID | None = None
    parent_group_name: str | None = None
    group_name: str
    group_code: str | None = None
    group_type: AssetGroupType
    description: str | None = None
    org_node_id: uuid.UUID | None = None
    org_node_name: str | None = None
    is_active: bool
    child_group_count: int = 0
    direct_asset_count: int = 0
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class AssetGroupTreeResponse(AssetGroupResponse):
    children: list["AssetGroupTreeResponse"] = Field(default_factory=list)


class AssetGroupMembershipCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    asset_uuids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("asset_uuids", "assetUuids"),
    )
    created_by: str = Field(..., min_length=1, max_length=150, validation_alias=AliasChoices("created_by", "createdBy"))


class AssetGroupMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    group_id: uuid.UUID
    asset_uuid: uuid.UUID
    asset_id: str | None = None
    asset_name: str | None = None
    asset_class: str | None = None
    asset_type: str | None = None
    asset_status: str | None = None
    org_node_id: uuid.UUID | None = None
    org_node_name: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None


AssetGroupTreeResponse.model_rebuild()
