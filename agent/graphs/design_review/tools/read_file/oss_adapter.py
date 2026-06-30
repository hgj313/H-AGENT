"""OSS FileID 适配器。

基于项目 oss.base.StorageService Protocol 的文件标识管理，支持：
- 文件上传与注册
- 基于 object_name 的 FileID 管理
- 预签名 URL 生成（支持多模态模型访问）
- 内容去重（SHA256 哈希）
- LRU 缓存（最近使用的文件元信息）

设计原则（v2 — 与项目 oss 模块统一）：
- 存储后端：通过 oss.di.OSSRegistry 注入的 StorageService Protocol
- object_name 即 FileID，无需额外生成
- 预签名 URL 支持设置过期时间，确保安全
- 缓存已访问文件的信息，减少 OSS 请求
- 兜底：Registry 未初始化时使用内嵌 _FallbackLocalAdapter（仅 dev/test）
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    from oss.base import (
        StorageService,
        UploadRequest,
        UploadResult,
        SignedURLRequest,
        SignedURLResult,
        ObjectMetadata,
        DownloadRequest,
        DownloadResult,
        StreamDownloadRequest,
        PublicURLRequest,
        PublicURLResult,
    )
    from oss.di import OSSRegistry
    OSS_BASE_AVAILABLE = True
except ImportError:
    OSS_BASE_AVAILABLE = False
    StorageService = None
    UploadRequest = None
    UploadResult = None
    SignedURLRequest = None
    SignedURLResult = None
    ObjectMetadata = None
    DownloadRequest = None
    DownloadResult = None
    StreamDownloadRequest = None
    PublicURLRequest = None
    PublicURLResult = None
    OSSRegistry = None

# 兼容旧导入名（外部可能仍引用）
OSS_AVAILABLE = OSS_BASE_AVAILABLE

logger = logging.getLogger(__name__)


# ── 兜底 Local 适配器（Registry 未初始化时）───────────────
class _FallbackLocalAdapter:
    """极简 Local 适配器，仅实现 read_file 用到的子集。

    适用：dev / test 时 OSSRegistry 尚未注册任何 adapter 的场景。
    生产应通过 api/main.py lifespan 显式注册 AliyunOSSAdapter。
    """

    backend_name: str = "local"

    def __init__(self, root: Path | None = None):
        from pathlib import Path
        self.root = Path(root or Path("uploads") / "read_file_fallback")
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, object_name: str) -> Path:
        return self.root / object_name.replace("/", "_").replace(":", "_")

    def upload_file(self, request: UploadRequest) -> UploadResult:
        target = self._resolve(request.object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(request.file_path, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
        return UploadResult(object_name=request.object_name, etag=None, version_id=None)

    def generate_signed_url(self, request: SignedURLRequest) -> SignedURLResult:
        return SignedURLResult(
            object_name=request.object_name,
            url=f"/api/v1/files/{request.object_name.split('/')[-1]}",
            method=request.method,
            expires_at=datetime.now(),
            signed_headers={},
        )

    def head_object(self, object_name: str) -> ObjectMetadata:
        path = self._resolve(object_name)
        if not path.exists():
            raise FileNotFoundError(object_name)
        return ObjectMetadata(
            object_name=object_name,
            content_length=path.stat().st_size,
            content_type=None,
            etag=None,
            last_modified=None,
            metadata={},
        )

    def download_file(self, request: DownloadRequest) -> DownloadResult:
        src = self._resolve(request.object_name)
        with open(src, "rb") as fsrc, open(request.target_path, "wb") as fdst:
            fdst.write(fsrc.read())
        return DownloadResult(
            object_name=request.object_name,
            target_path=str(request.target_path),
            written_bytes=Path(request.target_path).stat().st_size,
        )

    def stream_download(self, request: StreamDownloadRequest) -> Iterator[bytes]:
        with open(self._resolve(request.object_name), "rb") as f:
            while chunk := f.read(request.chunk_size):
                yield chunk

    def get_public_url(self, request: PublicURLRequest) -> PublicURLResult:
        return PublicURLResult(object_name=request.object_name, url="", cdn_url=None)

    # multipart / resumable / upload_stream 在 read_file 不使用
    def multipart_upload(self, request): return self.upload_file(request)  # type: ignore
    def resumable_upload(self, request): return self.upload_file(request)  # type: ignore
    def upload_stream(self, request):  # type: ignore
        target = self._resolve(request.object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as dst:
            while chunk := request.reader.read(64 * 1024):
                dst.write(chunk)
        return UploadResult(object_name=request.object_name, etag=None, version_id=None)


def _resolve_storage_adapter(explicit: Optional["StorageService"] = None) -> "StorageService":
    """解析用于 read_file 的 StorageService。

    优先级：
      1. 显式传入
      2. oss.di.OSSRegistry 已注册的 adapter
      3. provide_oss_client() 从 env 自动加载
      4. _FallbackLocalAdapter（仅 dev/test 兜底）
    """
    if explicit is not None:
        return explicit
    if not OSS_BASE_AVAILABLE:
        raise RuntimeError("oss.base 模块不可用，无法访问 StorageService")
    # 1) Registry 已注册
    try:
        return OSSRegistry.get_instance().get_adapter()
    except RuntimeError:
        pass
    # 2) env 自动加载
    try:
        from oss.di import provide_oss_client
        provide_oss_client()
        return OSSRegistry.get_instance().get_adapter()
    except RuntimeError:
        pass
    # 3) 兜底
    logger.warning(
        "OSSRegistry 未注册且 env 缺失，使用 _FallbackLocalAdapter（仅 dev/test）"
    )
    return _FallbackLocalAdapter()  # type: ignore[return-value]


@dataclass
class FileMetadata:
    object_name: str
    content_hash: str
    content_length: int
    content_type: str | None = None
    created_at: datetime | None = None
    last_accessed: datetime | None = None
    access_count: int = 0
    url_expires_at: datetime | None = None
    cached_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'object_name': self.object_name,
            'content_hash': self.content_hash,
            'content_length': self.content_length,
            'content_type': self.content_type,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_accessed': self.last_accessed.isoformat() if self.last_accessed else None,
            'access_count': self.access_count,
            'url_expires_at': self.url_expires_at.isoformat() if self.url_expires_at else None,
        }


class LRUCache:
    def __init__(self, max_size: int = 1000):
        self._max_size = max_size
        self._cache: dict[str, FileMetadata] = {}
        self._access_order: list[str] = []

    def get(self, key: str) -> FileMetadata | None:
        if key in self._cache:
            self._access_order.remove(key)
            self._access_order.append(key)
            self._cache[key].last_accessed = datetime.now()
            self._cache[key].access_count += 1
            return self._cache[key]
        return None

    def put(self, key: str, value: FileMetadata) -> None:
        if key in self._cache:
            self._access_order.remove(key)
        elif len(self._cache) >= self._max_size:
            oldest = self._access_order.pop(0)
            del self._cache[oldest]

        self._cache[key] = value
        self._access_order.append(key)

    def remove(self, key: str) -> None:
        if key in self._cache:
            del self._cache[key]
            self._access_order.remove(key)

    def clear(self) -> None:
        self._cache.clear()
        self._access_order.clear()

    def __len__(self) -> int:
        return len(self._cache)


class OSSFileIDAdapter:
    name: str = "OSSFileIDAdapter"

    def __init__(
        self,
        bucket_prefix: str = "file-id",
        url_expiry_seconds: int = 3600,
        cache_size: int = 1000,
        enable_dedup: bool = True,
        *,
        storage_adapter: "StorageService | None" = None,
    ) -> None:
        self._bucket_prefix = bucket_prefix.rstrip('/')
        self._url_expiry = url_expiry_seconds
        self._enable_dedup = enable_dedup
        self._cache = LRUCache(max_size=cache_size)
        # v2：通过 oss.base.StorageService Protocol 走 OSSRegistry，
        # 不再依赖 infrastructure.upload.UploadService / infrastructure.download.DownloadService
        self._storage_adapter: "StorageService" = _resolve_storage_adapter(storage_adapter)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.info(
            "OSSFileIDAdapter 初始化：storage=%s",
            type(self._storage_adapter).__name__,
        )

    @property
    def storage_adapter(self) -> "StorageService":
        """暴露底层 StorageService（用于测试 / 高级用法）。"""
        return self._storage_adapter

    @property
    def upload_service(self):
        """兼容旧调用：返回 self.storage_adapter（duck-type 兼容）。"""
        return self._storage_adapter

    @property
    def download_service(self):
        """兼容旧调用：返回 self.storage_adapter。"""
        return self._storage_adapter

    def compute_content_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def generate_object_name(
        self,
        original_filename: str,
        content_hash: str,
        subdir: str | None = None,
    ) -> str:
        ext = Path(original_filename).suffix.lower()
        parts = [self._bucket_prefix]

        if subdir:
            parts.append(subdir.strip('/'))

        parts.append(f"{content_hash[:16]}{ext}")
        return '/'.join(parts)

    async def upload_and_register(
        self,
        file_path: str | Path,
        object_name: str | None = None,
        content_type: str | None = None,
    ) -> FileMetadata:
        if not OSS_AVAILABLE:
            raise RuntimeError("OSS 模块不可用，无法上传文件")

        path = Path(file_path)
        content = path.read_bytes()
        content_hash = self.compute_content_hash(content)
        content_length = len(content)

        if object_name is None:
            object_name = self.generate_object_name(path.name, content_hash)

        if self._enable_dedup:
            existing = self._cache.get(object_name)
            if existing:
                self._logger.info(f"文件已存在，跳过上传: {object_name}")
                return existing

        # v2：直接走 oss.base.StorageService Protocol
        result = self._storage_adapter.upload_file(
            UploadRequest(
                object_name=object_name,
                file_path=str(path),
                content_type=content_type,
            )
        )

        metadata = FileMetadata(
            object_name=result.object_name,
            content_hash=content_hash,
            content_length=content_length,
            content_type=content_type or self._guess_content_type(path.name),
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=1,
        )

        self._cache.put(object_name, metadata)
        self._logger.info(f"文件已上传并注册: {object_name}")

        return metadata

    def register_existing(
        self,
        object_name: str,
        content_length: int,
        content_hash: str | None = None,
        content_type: str | None = None,
    ) -> FileMetadata:
        if content_hash is None:
            content_hash = self.compute_content_hash(b'')[:16] + object_name.split('/')[-1][:16]

        metadata = FileMetadata(
            object_name=object_name,
            content_hash=content_hash,
            content_length=content_length,
            content_type=content_type,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=0,
        )

        self._cache.put(object_name, metadata)
        return metadata

    def get_signed_url(
        self,
        object_name: str,
        expire_seconds: int | None = None,
        force_refresh: bool = False,
    ) -> str:
        if not OSS_AVAILABLE:
            raise RuntimeError("OSS 模块不可用，无法生成预签名 URL")

        cached = self._cache.get(object_name)

        if (not force_refresh
            and cached
            and cached.cached_url
            and cached.url_expires_at
            and cached.url_expires_at > datetime.now()):
            return cached.cached_url

        expiry = expire_seconds or self._url_expiry
        # v2：直接走 oss.base.StorageService Protocol.generate_signed_url
        result = self._storage_adapter.generate_signed_url(
            SignedURLRequest(
                object_name=object_name,
                expire_seconds=expiry,
            )
        )

        expires_at = result.expires_at or datetime.fromtimestamp(time.time() + expiry)

        if cached:
            cached.cached_url = result.url if hasattr(result, 'url') else result
            cached.url_expires_at = expires_at
        else:
            metadata = FileMetadata(
                object_name=object_name,
                content_hash='',
                content_length=0,
                content_type=None,
                cached_url=result.url if hasattr(result, 'url') else result,
                url_expires_at=expires_at,
            )
            self._cache.put(object_name, metadata)

        return result.url if hasattr(result, 'url') else result

    def get_file_id(self, object_name: str) -> str:
        return object_name

    def resolve_file_id(self, file_id: str) -> str:
        return file_id

    def is_cached(self, object_name: str) -> bool:
        return object_name in self._cache._cache

    def get_metadata(self, object_name: str) -> FileMetadata | None:
        return self._cache.get(object_name)

    def invalidate_cache(self, object_name: str) -> None:
        self._cache.remove(object_name)
        self._logger.info(f"缓存已失效: {object_name}")

    def clear_cache(self) -> None:
        self._cache.clear()
        self._logger.info("缓存已清空")

    def _guess_content_type(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml',
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.mp3': 'audio/mpeg',
            '.mp4': 'video/mp4',
            '.json': 'application/json',
            '.xml': 'application/xml',
            '.txt': 'text/plain',
            '.html': 'text/html',
        }
        return mime_types.get(ext, 'application/octet-stream')

    def prepare_for_multimodal_model(
        self,
        object_name: str,
        model_type: str = "vision",
    ) -> dict[str, Any]:
        signed_url = self.get_signed_url(object_name)

        if model_type == "vision":
            return {
                "type": "image_url",
                "image_url": {
                    "url": signed_url,
                    "detail": "auto",
                }
            }
        elif model_type == "audio":
            return {
                "type": "input_audio",
                "input_audio": {
                    "url": signed_url,
                    "format": self._guess_audio_format(object_name),
                }
            }
        else:
            return {
                "type": "text",
                "text": f"[文件访问: {object_name}]({signed_url})"
            }

    def _guess_audio_format(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        format_map = {
            '.mp3': 'mp3',
            '.wav': 'wav',
            '.flac': 'flac',
            '.m4a': 'm4a',
            '.ogg': 'ogg',
            '.webm': 'webm',
        }
        return format_map.get(ext, 'mp3')

    def get_stats(self) -> dict[str, Any]:
        return {
            'cache_size': len(self._cache),
            'max_cache_size': self._cache._max_size,
            'url_expiry_seconds': self._url_expiry,
            'dedup_enabled': self._enable_dedup,
            'bucket_prefix': self._bucket_prefix,
        }


_oss_file_id_adapter: OSSFileIDAdapter | None = None


def get_oss_file_id_adapter(
    bucket_prefix: str = "file-id",
    url_expiry_seconds: int = 3600,
) -> OSSFileIDAdapter:
    global _oss_file_id_adapter
    if _oss_file_id_adapter is None:
        _oss_file_id_adapter = OSSFileIDAdapter(
            bucket_prefix=bucket_prefix,
            url_expiry_seconds=url_expiry_seconds,
        )
    return _oss_file_id_adapter


def reset_oss_file_id_adapter() -> None:
    global _oss_file_id_adapter
    _oss_file_id_adapter = None