"""
OSS 上传相关 Schema。

设计目标：抽象出"OSS 直传"语义，对外只暴露 object_name + url + expires_at，
后端底层可自由切换 Local / Aliyun OSS / AWS S3 等。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field

from api.v1.schemas.files import FileType


class OSSUploadResponse(BaseModel):
    """OSS 上传响应。

    Fields:
      object_name: 对象名（"oss://bucket/key" 或 "local://bucket/key"），
                    业务侧只存这个字符串，与底层存储解耦。
      url:         访问 URL（local 模式 = /api/v1/files/{id}，
                    真实 OSS 模式 = 预签名 URL）
      expires_at:  预签名 URL 过期时间（local 模式 = 当前+默认有效期）
      file_id:     后端内部 ID，便于后续查询/删除
      filename:    原始文件名
      file_type:   文件类型
      file_size:   字节数
      idempotent_reused: 若 True 表示本次上传命中 hash 去重，未真实上传
      content_hash:      文件 SHA-256（去重 key）
    """

    object_name: str = Field(..., description="OSS 对象名，业务侧只存这个字段")
    url: str = Field(..., description="可直接访问的 URL")
    expires_at: datetime = Field(..., description="URL 过期时间")
    file_id: str
    filename: str
    file_type: FileType
    file_size: int = Field(..., ge=0)
    storage_backend: str = Field(
        default="local", description="local / oss / s3, 仅用于诊断"
    )
    idempotent_reused: bool = Field(
        default=False,
        description="True = 命中 hash 去重，未真实上传",
    )
    content_hash: Optional[str] = Field(
        default=None, description="文件 SHA-256（去重 key）",
    )


class OSSUploadError(BaseModel):
    """OSS 上传错误响应。"""

    error: str
    details: Optional[str] = None
    allowed_types: Optional[list[str]] = None
    max_size: Optional[int] = None


class ObjectMetadataResponse(BaseModel):
    """对象元信息查询响应（head_object）。

    字段对齐 oss.base.ObjectMetadata，
    额外加 exists / backend 便于业务判断。
    """

    object_name: str
    content_length: Optional[int] = None
    content_type: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    exists: bool = Field(..., description="对象是否存在（False = 404 业务化为 ok）")
    backend: str = Field(..., description="local / oss / s3, 仅用于诊断")


def default_expires_at(ttl_seconds: int = 3600) -> datetime:
    """默认 URL 过期时间。"""
    return datetime.now() + timedelta(seconds=ttl_seconds)


# ── Presigned Upload（直传流程的统一入口）────────────────
class PresignUploadRequest(BaseModel):
    """申请上传许可的入参。

    客户端先 POST 这个拿到 upload_url + public_url，
    然后 PUT 文件字节到 upload_url（OSS 直传，不经我们后端），
    之后用 public_url 作为可访问的 image_url。
    """

    bucket: str = Field(
        default="default",
        description="目标 bucket（业务侧分类：design-review-prd / design-review-image 等）",
    )
    filename: str = Field(
        ...,
        description="原始文件名（含扩展名，用于推断 content_type 和落盘文件名）",
    )
    content_type: Optional[str] = Field(
        default=None,
        description="MIME（默认从 filename 推断）",
    )
    ttl_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400 * 7,  # OSS V4 签名最长 7 天
        description="upload_url / public_url 的有效期",
    )


class PresignUploadResponse(BaseModel):
    """申请上传许可的返回。

    字段语义：
      file_id:       后端内部 ID（与生成 object_name 一一对应）
      object_name:   对象名（local://bucket/file-xxx 或 oss://bucket/key）
      upload_url:    **绝对 URL** —— 客户端 PUT 文件到这里（OSS 模式 = 真 OSS 签名 URL；
                     LocalStorage 模式 = /api/v1/oss/direct-upload/{file_id}）
      upload_method: HTTP 方法（永远 = "PUT"）
      public_url:    **绝对 URL** —— 文件上传后可被 fetch 拿到字节流
                     （视觉模型 fetch 这个；前端 <img src> 也用这个）
      expires_at:    upload_url / public_url 的过期时间
      storage_backend: "local" / "oss" / "s3"（诊断用）
      nonce:         **防重放一次性令牌** —— 32 字符 hex（UUID v4）。
                     客户端 PUT 直传时必须放在 X-Nonce header 里。
                     后端会用它做一次性消费 + file_id 绑定 + 过期校验。
    """

    file_id: str
    object_name: str
    upload_url: str
    upload_method: str = "PUT"
    public_url: str
    expires_at: datetime
    storage_backend: str = "local"
    bucket: str
    nonce: str
