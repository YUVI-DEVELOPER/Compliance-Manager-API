from typing import Any

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    file_name: str
    original_file_name: str
    content_type: str | None = None
    file_size: int
    access_url: str
    relative_path: str


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
