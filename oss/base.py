"""OSS 核心抽象定义。

该模块只定义协议、配置与请求/响应模型，不包含具体云厂商实现。
上传与下载业务模块仅依赖这里的抽象，以保证底层存储实现可替换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterator, Mapping, Protocol


ProgressCallback = callable


@dataclass(slots=True)
class OSSConfig:
    """阿里云 OSS 连接配置。"""

    region: str
    bucket: str
    access_key_id: str
    access_key_secret: str
    endpoint: str | None = None
    sts_token: str | None = None
    connect_timeout: float = 10.0
    readwrite_timeout: float = 20.0
    retry_max_attempts: int = 3
    signature_version: str = "v4"
    use_internal_endpoint: bool = False
    disable_ssl: bool = False
    use_path_style: bool = False
    user_agent: str = "hgj-agent-oss-module/1.0"


@dataclass(slots=True)
class UploadRequest:
    """普通文件上传请求。"""

    object_name: str
    file_path: str | Path
    metadata: Mapping[str, str] | None = None
    content_type: str | None = None
    progress_callback: callable | None = None


@dataclass(slots=True)
class MultipartUploadRequest(UploadRequest):
    """分片上传请求。"""

    part_size: int = 6 * 1024 * 1024
    parallel_num: int = 3


@dataclass(slots=True)
class ResumableUploadRequest(MultipartUploadRequest):
    """断点续传上传请求。"""

    checkpoint_dir: str | Path | None = None
    enable_checkpoint: bool = True


@dataclass(slots=True)
class StreamUploadRequest:
    """流式上传请求。"""

    object_name: str
    reader: BinaryIO
    metadata: Mapping[str, str] | None = None
    content_type: str | None = None
    part_size: int = 6 * 1024 * 1024
    parallel_num: int = 3
    progress_callback: callable | None = None


@dataclass(slots=True)
class DownloadRequest:
    """文件下载请求。"""

    object_name: str
    target_path: str | Path
    part_size: int = 6 * 1024 * 1024
    parallel_num: int = 3
    use_temp_file: bool = True
    enable_checkpoint: bool = False
    checkpoint_dir: str | Path | None = None


@dataclass(slots=True)
class StreamDownloadRequest:
    """流式下载请求。"""

    object_name: str
    chunk_size: int = 64 * 1024


@dataclass(slots=True)
class SignedURLRequest:
    """预签名 URL 请求。"""

    object_name: str
    expire_seconds: int = 900
    method: str = "GET"


@dataclass(slots=True)
class ObjectMetadata:
    """对象元信息。"""

    object_name: str
    content_length: int | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class UploadResult:
    """上传结果。"""

    object_name: str
    etag: str | None = None
    version_id: str | None = None
    upload_id: str | None = None
    request_id: str | None = None


@dataclass(slots=True)
class DownloadResult:
    """下载结果。"""

    object_name: str
    target_path: str
    written_bytes: int


@dataclass(slots=True)
class SignedURLResult:
    """预签名 URL 结果。"""

    object_name: str
    url: str
    method: str
    expires_at: datetime | None = None
    signed_headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class PublicURLRequest:
    """公共读对象 URL 请求。"""

    object_name: str


@dataclass(slots=True)
class PublicURLResult:
    """公共读对象 URL 结果。"""

    object_name: str
    url: str
    cdn_url: str | None = None


class StorageService(Protocol):
    """统一存储能力协议。

    上传与下载业务模块只依赖该协议，不依赖任何具体云厂商 SDK。
    """

    def upload_file(self, request: UploadRequest) -> UploadResult:
        """执行普通文件上传。"""

    def multipart_upload(self, request: MultipartUploadRequest) -> UploadResult:
        """执行分片上传。"""

    def resumable_upload(self, request: ResumableUploadRequest) -> UploadResult:
        """执行断点续传上传。"""

    def upload_stream(self, request: StreamUploadRequest) -> UploadResult:
        """执行流式上传。"""

    def download_file(self, request: DownloadRequest) -> DownloadResult:
        """下载文件到本地。"""

    def stream_download(self, request: StreamDownloadRequest) -> Iterator[bytes]:
        """流式下载对象内容。"""

    def generate_signed_url(self, request: SignedURLRequest) -> SignedURLResult:
        """生成私有对象预签名 URL。"""

    def get_public_url(self, request: PublicURLRequest) -> PublicURLResult:
        """获取公共读对象的直接访问 URL（无需签名）。"""

    def head_object(self, object_name: str) -> ObjectMetadata:
        """查询对象元信息。"""
