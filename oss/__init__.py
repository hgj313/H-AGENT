"""OSS 模块包导出。

子模块说明:
- base:     定义请求/响应模型与 StorageService 协议，不含 SDK 依赖
- aliyun_oss: alibabacloud_oss_v2 SDK 的具体实现（延迟导入）
- di:       注解式依赖注入容器
"""

from __future__ import annotations

from .base import (
    OSSConfig,
    UploadRequest,
    MultipartUploadRequest,
    ResumableUploadRequest,
    StreamUploadRequest,
    DownloadRequest,
    StreamDownloadRequest,
    SignedURLRequest,
    ObjectMetadata,
    UploadResult,
    DownloadResult,
    SignedURLResult,
    StorageService,
)

__all__ = [
    "OSSConfig",
    "UploadRequest",
    "MultipartUploadRequest",
    "ResumableUploadRequest",
    "StreamUploadRequest",
    "DownloadRequest",
    "StreamDownloadRequest",
    "SignedURLRequest",
    "ObjectMetadata",
    "UploadResult",
    "DownloadResult",
    "SignedURLResult",
    "StorageService",
]


def __getattr__(name: str):
    if name == "AliyunOSSAdapter":
        from .aliyun_oss import AliyunOSSAdapter
        return AliyunOSSAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")