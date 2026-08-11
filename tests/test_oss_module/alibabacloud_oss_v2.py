"""alibabacloud_oss_v2 SDK 的模拟实现。

用于在测试环境中运行 OSS 模块测试，无需安装真实的 SDK 依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, BinaryIO, Iterator, MutableMapping


@dataclass
class Config:
    region: str | None = None
    endpoint: str | None = None
    credentials_provider: Any = None
    connect_timeout: float = 10.0
    readwrite_timeout: float = 20.0
    retry_max_attempts: int = 3
    signature_version: str = "v4"
    use_internal_endpoint: bool = False
    disable_ssl: bool = False
    use_path_style: bool = False
    user_agent: str = ""


class StaticCredentialsProvider:
    def __init__(self, access_key_id: str, access_key_secret: str, sts_token: str | None = None):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.sts_token = sts_token


class Client:
    def __init__(self, config: Config, **kwargs):
        self._config = config

    def put_object(self, request: Any) -> Any:
        class R:
            etag = '"mock-etag-123"'
            version_id = "v1.0"
            request_id = "mock-req-id"
        return R()

    def get_object(self, request: Any) -> Any:
        class R:
            body: BinaryIO = __import__("io").BytesIO(b"mock content")
            status_code = 200
            headers = {}
        return R()

    def head_object(self, request: Any) -> Any:
        class R:
            content_length = 2048
            content_type = "application/octet-stream"
            etag = '"mock-etag"'
            last_modified = None
            metadata: MutableMapping[str, str] = {}
        return R()

    def presign(self, request: Any, **kwargs) -> Any:
        class R:
            url = f"https://mock.oss.com/{request.bucket}/{request.key}?signature=mock"
            method = "GET"
            expiration = None
            signed_headers: MutableMapping[str, str] = {}
        return R()


@dataclass
class UploadResult:
    upload_id: str | None = None
    etag: str | None = None
    version_id: str | None = None
    hash_crc64: str | None = None


@dataclass
class DownloadResult:
    written: int | None = None


class Uploader:
    def __init__(self, client: Client):
        self._client = client

    def upload_file(self, request: Any, filepath: str, **kwargs) -> UploadResult:
        return UploadResult(upload_id="mock-upload-id", etag='"mock-etag"')

    def upload_from(self, request: Any, reader: BinaryIO, **kwargs) -> UploadResult:
        return UploadResult(upload_id="mock-upload-id", etag='"mock-etag"')


class Downloader:
    def __init__(self, client: Client):
        self._client = client

    def download_file(self, request: Any, filepath: str, **kwargs) -> DownloadResult:
        return DownloadResult(written=1024)


class models:
    PutObjectRequest = None
    GetObjectRequest = None
    HeadObjectRequest = None


def _make_model(name: str) -> type:
    @dataclass
    class M:
        bucket: str | None = None
        key: str | None = None
        body: Any = None
        content_type: str | None = None
        metadata: MutableMapping[str, str] | None = None
        progress_fn: Any = None

    return M


class _Models:
    @staticmethod
    def __getattr__(name: str) -> type:
        return _make_model(name)


models = _Models()