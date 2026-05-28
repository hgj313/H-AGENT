"""Aliyun OSS 存储适配器。

实现 StorageService 协议，将 OSS 核心抽象转换为 alibabacloud_oss_v2 SDK 调用。
支持普通上传、分片上传、断点续传、流式上传，以及文件下载、流式下载与预签名 URL。
"""

from __future__ import annotations

import os
import time
import logging
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, Iterator, Any

import alibabacloud_oss_v2 as oss
from alibabacloud_oss_v2 import models

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


logger = logging.getLogger(__name__)


class AliyunOSSAdapter:
    """阿里云 OSS 适配器，实现 StorageService 协议。

    通过依赖注入框架使用，示例::

        from oss.di import provide_oss_client, oss_client

        client = provide_oss_client()
        adapter = AliyunOSSAdapter(client)

    或直接实例化::

        config = OSSConfig(
            region="cn-hangzhou",
            bucket="my-bucket",
            access_key_id="xxx",
            access_key_secret="xxx",
        )
        adapter = AliyunOSSAdapter.from_config(config)
    """

    def __init__(
        self,
        oss_client: oss.Client,
        bucket: str,
        default_endpoint: str | None = None,
    ) -> None:
        self._client = oss_client
        self._bucket = bucket
        self._default_endpoint = default_endpoint
        self._uploader = oss.Uploader(oss_client)
        self._downloader = oss.Downloader(oss_client)

    @classmethod
    def from_config(cls, config: OSSConfig) -> AliyunOSSAdapter:
        """根据 OSSConfig 配置创建适配器实例。"""
        oss_config = oss.Config(
            region=config.region,
            endpoint=config.endpoint,
            credentials_provider=oss.credentials.StaticCredentialsProvider(
                config.access_key_id,
                config.access_key_secret,
                config.sts_token,
            ),
            connect_timeout=config.connect_timeout,
            readwrite_timeout=config.readwrite_timeout,
            retry_max_attempts=config.retry_max_attempts,
            signature_version=config.signature_version,
            use_internal_endpoint=config.use_internal_endpoint,
            disable_ssl=config.disable_ssl,
            use_path_style=config.use_path_style,
            user_agent=config.user_agent,
        )
        oss_client = oss.Client(oss_config)
        return cls(oss_client, config.bucket, config.endpoint)

    def _make_progress_fn(
        self, callback: callable | None
    ) -> callable | None:
        """将标准化回调转换为 SDK 进度回调。"""
        if callback is None:
            return None

        def progress_fn(bytes_consumed: int, total_bytes: int | None) -> None:
            callback(bytes_consumed, total_bytes or 0)

        return progress_fn

    def upload_file(self, request: UploadRequest) -> UploadResult:
        """普通文件上传。

        小文件直接调用 PutObject，适合小于 100MB 的文件。
        """
        logger.info("普通上传: object=%s, file=%s", request.object_name, request.file_path)
        def _safe_header_value(value: str | None) -> str | None:
            if value is None:
                return None
            try:
                value.encode("ascii")
                return value
            except UnicodeEncodeError:
                import base64
                return base64.b64encode(value.encode("utf-8")).decode("ascii")

        metadata = None
        if request.metadata:
            metadata = {
                k: _safe_header_value(str(v)) for k, v in request.metadata.items()
            }
        req = models.PutObjectRequest(
            bucket=self._bucket,
            key=request.object_name,
            content_type=_safe_header_value(request.content_type),
            metadata=metadata,
        )
        upload_result = self._uploader.upload_file(req, str(request.file_path))
        logger.info("上传成功: object=%s, etag=%s", request.object_name, upload_result.etag)
        return UploadResult(
            object_name=request.object_name,
            etag=upload_result.etag,
            version_id=upload_result.version_id,
        )

    def multipart_upload(self, request: MultipartUploadRequest) -> UploadResult:
        """分片上传。

        大文件拆分为多个分片并行上传，提升吞吐与容错能力。
        """
        logger.info(
            "分片上传: object=%s, file=%s, part_size=%s, parallel=%s",
            request.object_name,
            request.file_path,
            request.part_size,
            request.parallel_num,
        )
        req = models.PutObjectRequest(
            bucket=self._bucket,
            key=request.object_name,
            content_type=request.content_type,
            metadata=dict(request.metadata) if request.metadata else None,
        )
        upload_result = self._uploader.upload_file(
            req,
            str(request.file_path),
            part_size=request.part_size,
            parallel_num=request.parallel_num,
        )
        logger.info(
            "分片上传完成: object=%s, upload_id=%s, etag=%s",
            request.object_name,
            upload_result.upload_id,
            upload_result.etag,
        )
        return UploadResult(
            object_name=request.object_name,
            etag=upload_result.etag,
            version_id=upload_result.version_id,
            upload_id=upload_result.upload_id,
        )

    def resumable_upload(self, request: ResumableUploadRequest) -> UploadResult:
        """断点续传上传。

        基于分片上传，记录上传进度至 checkpoint 文件。
        网络中断后可从断点恢复，避免重复上传已完成分片。
        """
        checkpoint_dir = str(request.checkpoint_dir or os.path.dirname(str(request.file_path)))
        logger.info(
            "断点续传上传: object=%s, file=%s, checkpoint_dir=%s, enable_checkpoint=%s",
            request.object_name,
            request.file_path,
            checkpoint_dir,
            request.enable_checkpoint,
        )
        req = models.PutObjectRequest(
            bucket=self._bucket,
            key=request.object_name,
            content_type=request.content_type,
            metadata=dict(request.metadata) if request.metadata else None,
        )
        upload_result = self._uploader.upload_file(
            req,
            str(request.file_path),
            part_size=request.part_size,
            parallel_num=request.parallel_num,
            enable_checkpoint=request.enable_checkpoint,
            checkpoint_dir=checkpoint_dir,
        )
        logger.info(
            "断点续传完成: object=%s, upload_id=%s",
            request.object_name,
            upload_result.upload_id,
        )
        return UploadResult(
            object_name=request.object_name,
            etag=upload_result.etag,
            version_id=upload_result.version_id,
            upload_id=upload_result.upload_id,
        )

    def upload_stream(self, request: StreamUploadRequest) -> UploadResult:
        """流式上传。

        通过迭代器或流对象上传数据，适合动态生成的数据源。
        """
        logger.info(
            "流式上传: object=%s, part_size=%s",
            request.object_name,
            request.part_size,
        )
        req = models.PutObjectRequest(
            bucket=self._bucket,
            key=request.object_name,
            content_type=request.content_type,
            metadata=dict(request.metadata) if request.metadata else None,
            progress_fn=self._make_progress_fn(request.progress_callback),
        )
        upload_result = self._uploader.upload_from(
            req,
            request.reader,
            part_size=request.part_size,
            parallel_num=request.parallel_num,
        )
        return UploadResult(
            object_name=request.object_name,
            etag=upload_result.etag,
            version_id=upload_result.version_id,
            upload_id=upload_result.upload_id,
        )

    def download_file(self, request: DownloadRequest) -> DownloadResult:
        """下载文件。

        支持分片并行下载和临时文件模式，提升大文件下载性能。
        """
        logger.info(
            "文件下载: object=%s -> %s, part_size=%s",
            request.object_name,
            request.target_path,
            request.part_size,
        )
        req = models.GetObjectRequest(
            bucket=self._bucket,
            key=request.object_name,
        )
        download_result = self._downloader.download_file(
            req,
            str(request.target_path),
            part_size=request.part_size,
            parallel_num=request.parallel_num,
            use_temp_file=request.use_temp_file,
            enable_checkpoint=request.enable_checkpoint,
            checkpoint_dir=str(request.checkpoint_dir) if request.checkpoint_dir else None,
        )
        logger.info(
            "文件下载完成: object=%s, written=%s",
            request.object_name,
            download_result.written,
        )
        return DownloadResult(
            object_name=request.object_name,
            target_path=str(request.target_path),
            written_bytes=download_result.written or 0,
        )

    def stream_download(self, request: StreamDownloadRequest) -> Iterator[bytes]:
        """流式下载。

        逐块 yield 数据，避免一次性加载大文件到内存。
        """
        logger.info("流式下载: object=%s, chunk_size=%s", request.object_name, request.chunk_size)
        req = models.GetObjectRequest(
            bucket=self._bucket,
            key=request.object_name,
        )
        result = self._client.get_object(req)
        remaining = request.chunk_size
        while True:
            chunk = result.body.read(remaining)
            if not chunk:
                break
            yield chunk
            remaining = request.chunk_size

    def generate_signed_url(self, request: SignedURLRequest) -> SignedURLResult:
        """生成私有文件预签名 URL。

        V4 签名有效期最长 7 天。适用于临时授权第三方下载或上传。
        """
        logger.info(
            "生成预签名URL: object=%s, expire=%ss, method=%s",
            request.object_name,
            request.expire_seconds,
            request.method,
        )
        expires = timedelta(seconds=request.expire_seconds)
        if request.method == "PUT":
            req = models.PutObjectRequest(bucket=self._bucket, key=request.object_name)
        else:
            req = models.GetObjectRequest(bucket=self._bucket, key=request.object_name)
        presign_result = self._client.presign(req, expires=expires)
        return SignedURLResult(
            object_name=request.object_name,
            url=presign_result.url,
            method=request.method,
            expires_at=presign_result.expiration,
            signed_headers=dict(presign_result.signed_headers) if presign_result.signed_headers else {},
        )

    def head_object(self, object_name: str) -> ObjectMetadata:
        """查询对象元信息。

        返回对象大小、内容类型、ETag、最后修改时间等。
        """
        req = models.HeadObjectRequest(bucket=self._bucket, key=object_name)
        result = self._client.head_object(req)
        return ObjectMetadata(
            object_name=object_name,
            content_length=result.content_length,
            content_type=result.content_type,
            etag=result.etag,
            last_modified=result.last_modified,
            metadata=dict(result.metadata) if result.metadata else {},
        )


StorageService.register(AliyunOSSAdapter)