"""文件上传业务模块。

通过 @oss_inject 依赖注入 StorageService 协议实现，支持:
- 普通文件上传
- 分片并行上传
- 断点续传上传（支持网络中断恢复）
- 进度实时回调
- 指数退避重试与异常捕获
- 自动选择上传策略（根据文件大小智能切换）

依赖关系:
  UploadService ──@oss_inject──> StorageService (协议)
                                    │
                          AliyunOSSAdapter (alibabacloud_oss_v2)
                          MinioAdapter   (MinIO)
                          S3Adapter      (AWS S3)

使用示例:

  from infrastructure.upload import UploadService, UploadPolicy

  service = UploadService()
  result = service.upload("docs/readme.md", "readme.md")

  # 带进度回调
  def on_progress(uploaded, total):
      print(f"进度: {uploaded}/{total} bytes ({uploaded*100//total}%)")

  service.upload("large_video.mp4", "video/large_video.mp4",
                 policy=UploadPolicy.MULTIPART,
                 progress_callback=on_progress)
"""

from __future__ import annotations

import os
import time
import logging
import enum
from pathlib import Path
from typing import Callable, Any

from oss.base import (
    UploadRequest,
    MultipartUploadRequest,
    ResumableUploadRequest,
    StreamUploadRequest,
    UploadResult,
    ObjectMetadata,
    StorageService,
)
from oss.di import OSSClient, oss_inject, OSSInjector, OSSRegistry


logger = logging.getLogger(__name__)

DEFAULT_SMALL_FILE_THRESHOLD = 100 * 1024 * 1024
DEFAULT_LARGE_FILE_THRESHOLD = 5 * 1024 * 1024 * 1024


class UploadPolicy(enum.Enum):
    AUTO = "auto"
    SIMPLE = "simple"
    MULTIPART = "multipart"
    RESUMABLE = "resumable"


class UploadError(Exception):
    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self._cause = cause

    @property
    def cause(self) -> Exception | None:
        return self._cause


class UploadService(OSSInjector[StorageService]):
    """文件上传服务。

    封装所有上传策略，通过依赖注入获取底层存储适配器。
    """

    def __init__(
        self,
        small_file_threshold: int = DEFAULT_SMALL_FILE_THRESHOLD,
        large_file_threshold: int = DEFAULT_LARGE_FILE_THRESHOLD,
        default_part_size: int = 6 * 1024 * 1024,
        default_parallel_num: int = 3,
        max_retry_attempts: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._small_threshold = small_file_threshold
        self._large_threshold = large_file_threshold
        self._default_part_size = default_part_size
        self._default_parallel = default_parallel_num
        self._max_retry = max_retry_attempts
        self._retry_base_delay = retry_base_delay
        self._progress_callbacks: dict[str, Callable[[int, int], None]] = {}

    @property
    def _oss(self) -> StorageService:
        return self._resolve_oss()

    def _select_policy(
        self,
        file_path: Path | str,
        explicit_policy: UploadPolicy,
    ) -> UploadPolicy:
        if explicit_policy != UploadPolicy.AUTO:
            return explicit_policy

        path = Path(file_path)
        if not path.exists():
            return UploadPolicy.SIMPLE
        size = path.stat().st_size
        if size < self._small_threshold:
            return UploadPolicy.SIMPLE
        if size > self._large_threshold:
            return UploadPolicy.RESUMABLE
        return UploadPolicy.MULTIPART

    def _execute_with_retry(
        self,
        func: Callable[[], UploadResult],
        object_name: str,
    ) -> UploadResult:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retry + 1):
            try:
                return func()
            except Exception as e:
                last_error = e
                if attempt < self._max_retry:
                    delay = self._retry_base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "上传失败 (尝试 %s/%s)，%ss 后重试: object=%s, error=%s",
                        attempt,
                        self._max_retry,
                        delay,
                        object_name,
                        str(e),
                    )
                    time.sleep(delay)
                else:
                    logger.error("上传最终失败: object=%s, error=%s", object_name, str(e))
        raise UploadError(f"上传失败，已重试 {self._max_retry} 次: {object_name}", last_error)

    def upload(
        self,
        file_path: str | Path,
        object_name: str,
        metadata: dict[str, str] | None = None,
        content_type: str | None = None,
        policy: UploadPolicy = UploadPolicy.AUTO,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> UploadResult:
        path = Path(file_path)
        if not path.exists():
            raise UploadError(f"文件不存在: {path}")

        policy = self._select_policy(path, policy)
        file_size = path.stat().st_size

        logger.info(
            "开始上传: object=%s, file=%s, size=%s, policy=%s",
            object_name,
            path,
            file_size,
            policy.value,
        )

        if progress_callback:
            self._progress_callbacks[object_name] = progress_callback

        def _do_upload() -> UploadResult:
            if policy == UploadPolicy.SIMPLE:
                logger.debug("使用普通上传: %s", object_name)
                request = UploadRequest(
                    object_name=object_name,
                    file_path=path,
                    metadata=metadata,
                    content_type=content_type,
                    progress_callback=progress_callback,
                )
                return self._oss.upload_file(request)

            elif policy == UploadPolicy.MULTIPART:
                logger.debug("使用分片上传: %s", object_name)
                request = MultipartUploadRequest(
                    object_name=object_name,
                    file_path=path,
                    metadata=metadata,
                    content_type=content_type,
                    part_size=self._default_part_size,
                    parallel_num=self._default_parallel,
                )
                return self._oss.multipart_upload(request)

            else:
                logger.debug("使用断点续传: %s", object_name)
                request = ResumableUploadRequest(
                    object_name=object_name,
                    file_path=path,
                    metadata=metadata,
                    content_type=content_type,
                    part_size=self._default_part_size,
                    parallel_num=self._default_parallel,
                    checkpoint_dir=str(path.parent / ".oss_checkpoint"),
                    enable_checkpoint=True,
                )
                return self._oss.resumable_upload(request)

        result = self._execute_with_retry(_do_upload, object_name)
        self._progress_callbacks.pop(object_name, None)
        return result

    def upload_stream(
        self,
        reader: Any,
        object_name: str,
        total_size: int | None = None,
        metadata: dict[str, str] | None = None,
        content_type: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> UploadResult:
        request = StreamUploadRequest(
            object_name=object_name,
            reader=reader,
            metadata=metadata,
            content_type=content_type,
            part_size=self._default_part_size,
            parallel_num=self._default_parallel,
            progress_callback=progress_callback,
        )

        def _do() -> UploadResult:
            return self._oss.upload_stream(request)

        return self._execute_with_retry(_do, object_name)

    def check_upload_status(self, object_name: str) -> ObjectMetadata:
        return self._oss.head_object(object_name)


def simple_upload(
    file_path: str | Path,
    object_name: str,
    metadata: dict[str, str] | None = None,
    content_type: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> UploadResult:
    service = UploadService()
    return service.upload(
        file_path,
        object_name,
        metadata=metadata,
        content_type=content_type,
        policy=UploadPolicy.SIMPLE,
        progress_callback=progress_callback,
    )


def multipart_upload(
    file_path: str | Path,
    object_name: str,
    part_size: int = 6 * 1024 * 1024,
    parallel_num: int = 3,
    metadata: dict[str, str] | None = None,
    content_type: str | None = None,
) -> UploadResult:
    service = UploadService()
    return service.upload(
        file_path,
        object_name,
        metadata=metadata,
        content_type=content_type,
        policy=UploadPolicy.MULTIPART,
    )


def resumable_upload(
    file_path: str | Path,
    object_name: str,
    checkpoint_dir: str | Path | None = None,
    part_size: int = 6 * 1024 * 1024,
    parallel_num: int = 3,
    metadata: dict[str, str] | None = None,
    content_type: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> UploadResult:
    service = UploadService()
    return service.upload(
        file_path,
        object_name,
        metadata=metadata,
        content_type=content_type,
        policy=UploadPolicy.RESUMABLE,
        progress_callback=progress_callback,
    )


class BatchUploader:
    def __init__(
        self,
        max_concurrent: int = 3,
        max_retry_attempts: int = 3,
    ) -> None:
        self._service = UploadService(max_retry_attempts=max_retry_attempts)
        self._max_concurrent = max_concurrent

    def upload_batch(
        self,
        files: list[tuple[str | Path, str]],
        policy: UploadPolicy = UploadPolicy.AUTO,
        on_file_complete: Callable[[str, UploadResult], None] | None = None,
        on_file_error: Callable[[str, Exception], None] | None = None,
    ) -> dict[str, UploadResult | Exception]:
        results: dict[str, UploadResult | Exception] = {}
        for local_path, object_name in files:
            try:
                result = self._service.upload(
                    local_path,
                    object_name,
                    policy=policy,
                )
                results[object_name] = result
                if on_file_complete:
                    on_file_complete(object_name, result)
            except Exception as e:
                results[object_name] = e
                if on_file_error:
                    on_file_error(object_name, e)
                logger.error("批量上传失败: object=%s, error=%s", object_name, str(e))
        return results