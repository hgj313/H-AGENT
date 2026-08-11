"""infrastructure 模块包。

提供基于 OSS 核心抽象的业务能力模块。

子模块:
- upload: 文件上传服务（含普通上传、分片上传、断点续传）
- download: 文件下载服务（含文件下载、流式下载、预签名 URL）
"""

from __future__ import annotations

from .upload import (
    UploadService,
    UploadPolicy,
    UploadError,
    BatchUploader,
    simple_upload,
    multipart_upload,
    resumable_upload,
)

from .download import (
    DownloadService,
    DownloadError,
    DownloadProgressTracker,
    download_file,
    signed_url_for_download,
    signed_url_for_upload,
)

__all__ = [
    "UploadService",
    "UploadPolicy",
    "UploadError",
    "BatchUploader",
    "simple_upload",
    "multipart_upload",
    "resumable_upload",
    "DownloadService",
    "DownloadError",
    "DownloadProgressTracker",
    "download_file",
    "signed_url_for_download",
    "signed_url_for_upload",
]