"""
文件相关 Schema。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class FileType(str, Enum):
    """支持的文件类型。"""
    DOCUMENT = "document"      # 文档: pdf, doc, docx, md, txt
    IMAGE = "image"            # 图片: jpg, jpeg, png, gif, webp
    SPREADSHEET = "spreadsheet"  # 表格: xls, xlsx, csv
    ARCHIVE = "archive"        # 压缩包: zip, rar, 7z
    OTHER = "other"


ALLOWED_EXTENSIONS: dict[FileType, set[str]] = {
    FileType.DOCUMENT: {".pdf", ".doc", ".docx", ".md", ".txt", ".rtf"},
    FileType.IMAGE: {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
    FileType.SPREADSHEET: {".xls", ".xlsx", ".csv"},
    FileType.ARCHIVE: {".zip", ".rar", ".7z"},
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


class FileUploadRequest(BaseModel):
    """文件上传请求。"""
    file_type: Optional[FileType] = None
    description: Optional[str] = None


class FileUploadResponse(BaseModel):
    """文件上传响应。"""
    file_id: str
    filename: str
    file_type: FileType
    file_size: int
    upload_time: datetime = Field(default_factory=datetime.now)
    file_path: str
    url: Optional[str] = None


class FileInfo(BaseModel):
    """文件信息。"""
    file_id: str
    filename: str
    file_type: FileType
    file_size: int
    upload_time: datetime
    file_path: str
    description: Optional[str] = None


class FileValidationError(BaseModel):
    """文件验证错误。"""
    error: str
    details: Optional[str] = None
    allowed_types: Optional[list[str]] = None
    max_size: Optional[int] = None


class UploadProgress(BaseModel):
    """上传进度。"""
    file_id: str
    filename: str
    progress: float = Field(..., ge=0, le=1, description="进度 0-1")
    status: str = "uploading"  # uploading, processing, completed, error
    error: Optional[str] = None
