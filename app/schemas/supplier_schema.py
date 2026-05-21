import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SupplierCreate(BaseModel):
    supplier_name: str = Field(..., min_length=1, max_length=250)
    supplier_type: str = Field(..., min_length=1, max_length=50)

    supplier_add1: str | None = Field(default=None, max_length=250)
    supplier_add2: str | None = Field(default=None, max_length=250)
    supplier_city: str | None = Field(default=None, max_length=150)
    supplier_pincode: str | None = Field(default=None, max_length=10)
    supplier_state: str | None = Field(default=None, max_length=150)
    supplier_country: str | None = Field(default=None, max_length=10)

    contact_name: str | None = Field(default=None, max_length=150)
    contact_email: EmailStr | None = Field(default=None, max_length=150)
    contact_phone: str | None = Field(default=None, max_length=50)

    created_by: str | None = Field(default=None, max_length=150)


class SupplierUpdate(BaseModel):
    supplier_name: str | None = Field(default=None, min_length=1, max_length=250)
    supplier_type: str | None = Field(default=None, max_length=50)

    supplier_add1: str | None = Field(default=None, max_length=250)
    supplier_add2: str | None = Field(default=None, max_length=250)
    supplier_city: str | None = Field(default=None, max_length=150)
    supplier_pincode: str | None = Field(default=None, max_length=10)
    supplier_state: str | None = Field(default=None, max_length=150)
    supplier_country: str | None = Field(default=None, max_length=10)

    contact_name: str | None = Field(default=None, max_length=150)
    contact_email: EmailStr | None = Field(default=None, max_length=150)
    contact_phone: str | None = Field(default=None, max_length=50)

    modified_by: str | None = Field(default=None, max_length=150)


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supplier_id: uuid.UUID
    supplier_name: str
    supplier_type: str | None = None

    supplier_add1: str | None = None
    supplier_add2: str | None = None
    supplier_city: str | None = None
    supplier_pincode: str | None = None
    supplier_state: str | None = None
    supplier_country: str | None = None

    contact_name: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None

    enrolled_dt: datetime | None = None

    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
