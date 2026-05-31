"""OSS FileID 适配器。

基于 OSS 存储服务的文件标识管理，支持：
- 文件上传与注册
- 基于 object_name 的 FileID 管理
- 预签名 URL 生成（支持多模态模型访问）
- 内容去重（SHA256 哈希）
- LRU 缓存（最近使用的文件元信息）

设计原则：
- object_name 即 FileID，无需额外生成
- 预签名 URL 支持设置过期时间，确保安全
- 缓存已访问文件的信息，减少 OSS 请求
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from oss.base import (
        StorageService,
        UploadRequest,
        ObjectMetadata,
        SignedURLRequest,
        SignedURLResult,
        UploadResult,
    )
    from infrastructure.upload import UploadService
    from infrastructure.download import DownloadService
    OSS_AVAILABLE = True
except ImportError:
    OSS_AVAILABLE = False
    StorageService = None
    UploadRequest = None
    ObjectMetadata = None
    SignedURLRequest = None
    SignedURLResult = None
    UploadResult = None
    UploadService = None
    DownloadService = None

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._bucket_prefix = bucket_prefix.rstrip('/')
        self._url_expiry = url_expiry_seconds
        self._enable_dedup = enable_dedup
        self._cache = LRUCache(max_size=cache_size)
        self._upload_service: UploadService | None = None
        self._download_service: DownloadService | None = None
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def upload_service(self) -> UploadService | None:
        if not OSS_AVAILABLE:
            self._logger.warning("OSS 模块不可用")
            return None
        if self._upload_service is None:
            self._upload_service = UploadService()
        return self._upload_service

    @property
    def download_service(self) -> DownloadService | None:
        if not OSS_AVAILABLE:
            self._logger.warning("OSS 模块不可用")
            return None
        if self._download_service is None:
            self._download_service = DownloadService()
        return self._download_service

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

        result = self.upload_service.upload_file(
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
        request = SignedURLRequest(
            object_name=object_name,
            expire_seconds=expiry,
        )

        service = self.download_service
        if service is None:
            raise RuntimeError("下载服务不可用")

        result = service.get_signed_url(object_name, expire_seconds=expiry)

        expires_at = datetime.fromtimestamp(time.time() + expiry)

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