"""文件下载业务模块。

通过 @oss_inject 依赖注入 StorageService 协议实现，支持:
- 文件下载（支持分片并行与临时文件模式）
- 流式下载（按块读取，避免大文件占满内存）
- 私有文件预签名 URL 生成（临时授权第三方访问）
- 下载进度监听
- 指数退避重试与异常捕获
- 断点续传下载（支持网络中断恢复）

依赖关系:
  DownloadService ──@oss_inject──> StorageService (协议)
                                      │
                            AliyunOSSAdapter (alibabacloud_oss_v2)
                            MinioAdapter   (MinIO)
                            S3Adapter      (AWS S3)

使用示例:

  from infrastructure.download import DownloadService, signed_url_for_upload

  service = DownloadService()
  result = service.download("video/demo.mp4", "local_video.mp4")

  # 流式下载（适合大文件或实时处理场景）
  for chunk in service.stream_download("large_dataset.csv"):
      process(chunk)

  # 获取私有文件的临时访问地址
  url_info = service.get_signed_url("private/doc.pdf", expire_seconds=3600)
  print(f"下载地址: {url_info.url}")
  print(f"有效期至: {url_info.expires_at}")
"""

from __future__ import annotations

import os
import time
import logging
from pathlib import Path
from typing import Callable, Any, Iterator

from oss.base import (
    DownloadRequest,
    StreamDownloadRequest,
    SignedURLRequest,
    DownloadResult,
    SignedURLResult,
    ObjectMetadata,
    StorageService,
)
from oss.di import OSSClient, oss_inject, OSSInjector, OSSRegistry


logger = logging.getLogger(__name__)

DEFAULT_PART_SIZE = 6 * 1024 * 1024


class DownloadError(Exception):
    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self._cause = cause

    @property
    def cause(self) -> Exception | None:
        return self._cause


class DownloadService(OSSInjector[StorageService]):
    """文件下载服务。

    封装所有下载策略，通过依赖注入获取底层存储适配器。
    """

    def __init__(
        self,
        default_part_size: int = DEFAULT_PART_SIZE,
        default_parallel_num: int = 3,
        use_temp_file: bool = True,
        max_retry_attempts: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._default_part_size = default_part_size
        self._default_parallel = default_parallel_num
        self._use_temp_file = use_temp_file
        self._max_retry = max_retry_attempts
        self._retry_base_delay = retry_base_delay

    @property
    def _oss(self) -> StorageService:
        return self._resolve_oss()

    def _ensure_parent_dir(self, file_path: Path) -> None:
        parent = file_path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)

    def _execute_with_retry(
        self,
        func: Callable[[], DownloadResult],
        object_name: str,
    ) -> DownloadResult:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retry + 1):
            try:
                return func()
            except Exception as e:
                last_error = e
                if attempt < self._max_retry:
                    delay = self._retry_base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "下载失败 (尝试 %s/%s)，%ss 后重试: object=%s, error=%s",
                        attempt,
                        self._max_retry,
                        delay,
                        object_name,
                        str(e),
                    )
                    time.sleep(delay)
                else:
                    logger.error("下载最终失败: object=%s, error=%s", object_name, str(e))
        raise DownloadError(f"下载失败，已重试 {self._max_retry} 次: {object_name}", last_error)

    def download(
        self,
        object_name: str,
        target_path: str | Path,
        part_size: int | None = None,
        parallel_num: int | None = None,
        enable_checkpoint: bool = False,
        checkpoint_dir: str | Path | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DownloadResult:
        path = Path(target_path)
        self._ensure_parent_dir(path)

        part_size = part_size or self._default_part_size
        parallel_num = parallel_num or self._default_parallel

        logger.info(
            "开始下载: object=%s -> %s, part_size=%s, parallel=%s",
            object_name,
            path,
            part_size,
            parallel_num,
        )

        def _do_download() -> DownloadResult:
            request = DownloadRequest(
                object_name=object_name,
                target_path=path,
                part_size=part_size,
                parallel_num=parallel_num,
                use_temp_file=self._use_temp_file,
                enable_checkpoint=enable_checkpoint,
                checkpoint_dir=str(checkpoint_dir) if checkpoint_dir else None,
            )
            return self._oss.download_file(request)

        return self._execute_with_retry(_do_download, object_name)

    def stream_download(
        self,
        object_name: str,
        chunk_size: int = 64 * 1024,
    ) -> Iterator[bytes]:
        logger.info("开始流式下载: object=%s, chunk_size=%s", object_name, chunk_size)
        request = StreamDownloadRequest(
            object_name=object_name,
            chunk_size=chunk_size,
        )
        yield from self._oss.stream_download(request)

    def download_to_stream(
        self,
        object_name: str,
        writer: Any,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        total_written = 0
        for chunk in self.stream_download(object_name):
            writer.write(chunk)
            total_written += len(chunk)
            if progress_callback:
                meta = self._oss.head_object(object_name)
                total_size = meta.content_length or 0
                progress_callback(total_written, total_size)
        return total_written

    def get_signed_url(
        self,
        object_name: str,
        expire_seconds: int = 900,
        method: str = "GET",
    ) -> SignedURLResult:
        logger.info(
            "生成预签名URL: object=%s, expire=%ss, method=%s",
            object_name,
            expire_seconds,
            method,
        )
        request = SignedURLRequest(
            object_name=object_name,
            expire_seconds=expire_seconds,
            method=method,
        )
        return self._oss.generate_signed_url(request)

    def check_object_exists(self, object_name: str) -> bool:
        try:
            self._oss.head_object(object_name)
            return True
        except Exception:
            return False

    def get_object_metadata(self, object_name: str) -> ObjectMetadata:
        return self._oss.head_object(object_name)


def download_file(
    object_name: str,
    target_path: str | Path,
    part_size: int | None = None,
    parallel_num: int | None = None,
) -> DownloadResult:
    service = DownloadService()
    return service.download(object_name, target_path, part_size, parallel_num)


def signed_url_for_download(
    object_name: str,
    expire_seconds: int = 3600,
) -> str:
    service = DownloadService()
    result = service.get_signed_url(object_name, expire_seconds, "GET")
    return result.url


def signed_url_for_upload(
    object_name: str,
    expire_seconds: int = 3600,
) -> str:
    service = DownloadService()
    result = service.get_signed_url(object_name, expire_seconds, "PUT")
    return result.url


class DownloadProgressTracker:
    def __init__(self, total_bytes: int | None = None) -> None:
        self._total = total_bytes
        self._downloaded = 0
        self._last_report = 0

    def update(self, bytes_delta: int) -> None:
        self._downloaded += bytes_delta
        if self._total and self._downloaded >= self._total:
            self._report_progress()

    def _report_progress(self) -> None:
        percent = (self._downloaded * 100 // self._total) if self._total else 0
        logger.info(
            "下载进度: %s / %s bytes (%s%%)",
            self._downloaded,
            self._total or "未知",
            percent,
        )

    def get_progress(self) -> tuple[int, int | None]:
        return self._downloaded, self._total