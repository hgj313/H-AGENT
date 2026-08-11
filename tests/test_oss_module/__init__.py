"""OSS 模块功能验证用例（无 SDK 依赖版本）。

测试覆盖:
1. 核心抽象模型（base.py）—— 请求/响应结构正确性
2. 依赖注入机制（di.py）—— 注册、注入、解包流程
3. 上传服务（infrastructure/upload）—— 策略选择、重试逻辑、进度回调
4. 下载服务（infrastructure/download）—— 签名URL、流式下载、进度追踪
5. 模块间解耦验证 —— 替换底层适配器不影响业务层
"""

from __future__ import annotations

import os
import sys
import io
import time
import tempfile
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from oss.base import (
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
from oss.di import OSSRegistry, OSSClient, oss_inject, OSSInjector

try:
    from oss import AliyunOSSAdapter
except ImportError:
    AliyunOSSAdapter = None


class TestOSSModels:
    """测试 OSS 核心数据模型。"""

    def test_oss_config_defaults(self):
        config = OSSConfig(
            region="cn-hangzhou",
            bucket="test-bucket",
            access_key_id="ak",
            access_key_secret="sk",
        )
        assert config.region == "cn-hangzhou"
        assert config.bucket == "test-bucket"
        assert config.retry_max_attempts == 3
        assert config.connect_timeout == 10.0
        assert config.user_agent.startswith("hgj-agent")

    def test_upload_request(self):
        request = UploadRequest(
            object_name="docs/readme.md",
            file_path="/tmp/readme.md",
            metadata={"author": "test"},
            content_type="text/markdown",
        )
        assert request.object_name == "docs/readme.md"
        assert request.metadata == {"author": "test"}
        assert request.content_type == "text/markdown"

    def test_multipart_upload_request(self):
        request = MultipartUploadRequest(
            object_name="video/large.mp4",
            file_path="/tmp/large.mp4",
            part_size=10 * 1024 * 1024,
            parallel_num=5,
        )
        assert request.part_size == 10 * 1024 * 1024
        assert request.parallel_num == 5
        assert isinstance(request, UploadRequest)

    def test_resumable_upload_request(self):
        request = ResumableUploadRequest(
            object_name="backup/data.zip",
            file_path="/tmp/data.zip",
            checkpoint_dir="/tmp/checkpoints",
            enable_checkpoint=True,
        )
        assert request.enable_checkpoint is True
        assert request.checkpoint_dir == "/tmp/checkpoints"

    def test_download_request(self):
        request = DownloadRequest(
            object_name="images/photo.jpg",
            target_path="/tmp/photo.jpg",
            part_size=8 * 1024 * 1024,
        )
        assert request.part_size == 8 * 1024 * 1024
        assert request.enable_checkpoint is False

    def test_signed_url_request(self):
        request = SignedURLRequest(
            object_name="private/report.pdf",
            expire_seconds=7200,
            method="GET",
        )
        assert request.expire_seconds == 7200
        assert request.method == "GET"

    def test_object_metadata(self):
        meta = ObjectMetadata(
            object_name="data.json",
            content_length=1024,
            content_type="application/json",
            etag='"abc123"',
        )
        assert meta.content_length == 1024
        assert meta.etag == '"abc123"'

    def test_upload_result(self):
        result = UploadResult(
            object_name="test.txt",
            etag='"etag123"',
            version_id="v1",
            upload_id="uid123",
            request_id="req123",
        )
        assert result.etag == '"etag123"'
        assert result.upload_id == "uid123"

    def test_download_result(self):
        result = DownloadResult(
            object_name="test.txt",
            target_path="/tmp/test.txt",
            written_bytes=2048,
        )
        assert result.written_bytes == 2048


class MockStorageAdapter:
    """完全模拟 StorageService 协议，供测试使用。"""

    _call_log: list[str] = []
    _upload_count: int = 0
    _fail_next: int = 0

    def upload_file(self, request: UploadRequest) -> UploadResult:
        self._call_log.append(f"upload_file:{request.object_name}")
        MockStorageAdapter._upload_count += 1
        if MockStorageAdapter._fail_next > 0:
            MockStorageAdapter._fail_next -= 1
            raise ConnectionError(f"Simulated network error (upload #{MockStorageAdapter._upload_count})")
        return UploadResult(
            object_name=request.object_name,
            etag=f"etag-{request.object_name}",
            version_id="v1",
            request_id="mock-request-id",
        )

    def multipart_upload(self, request: MultipartUploadRequest) -> UploadResult:
        self._call_log.append(f"multipart_upload:{request.object_name}")
        return UploadResult(
            object_name=request.object_name,
            etag=f"etag-{request.object_name}",
            upload_id="mock-upload-id",
        )

    def resumable_upload(self, request: ResumableUploadRequest) -> UploadResult:
        self._call_log.append(f"resumable_upload:{request.object_name}")
        return UploadResult(
            object_name=request.object_name,
            etag=f"etag-{request.object_name}",
            upload_id="mock-upload-id",
        )

    def upload_stream(self, request: StreamUploadRequest) -> UploadResult:
        self._call_log.append(f"upload_stream:{request.object_name}")
        return UploadResult(object_name=request.object_name, etag="etag-mock")

    def download_file(self, request: DownloadRequest) -> DownloadResult:
        self._call_log.append(f"download_file:{request.object_name}")
        return DownloadResult(
            object_name=request.object_name,
            target_path=str(request.target_path),
            written_bytes=1024,
        )

    def stream_download(self, request: StreamDownloadRequest) -> Iterator[bytes]:
        self._call_log.append(f"stream_download:{request.object_name}")
        yield b"chunk1"
        yield b"chunk2"

    def generate_signed_url(self, request: SignedURLRequest) -> SignedURLResult:
        self._call_log.append(f"generate_signed_url:{request.object_name}")
        return SignedURLResult(
            object_name=request.object_name,
            url=f"https://mock.oss.com/{request.object_name}?signature=mock",
            method=request.method,
            expires_at=None,
        )

    def head_object(self, object_name: str) -> ObjectMetadata:
        self._call_log.append(f"head_object:{object_name}")
        return ObjectMetadata(
            object_name=object_name,
            content_length=2048,
            content_type="application/octet-stream",
            etag='"mock-etag"',
        )

    @classmethod
    def reset_log(cls):
        cls._call_log.clear()
        cls._upload_count = 0
        cls._fail_next = 0


class TestDI:
    """测试依赖注入机制。"""

    def setup_method(self):
        OSSRegistry.get_instance().clear()
        MockStorageAdapter.reset_log()

    def teardown_method(self):
        OSSRegistry.get_instance().clear()

    def test_registry_register_and_get(self):
        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)
        retrieved = OSSRegistry.get_instance().get_adapter()
        assert retrieved is mock
        assert isinstance(retrieved, MockStorageAdapter)

    def test_registry_register_from_config_requires_sdk(self):
        config = OSSConfig(
            region="cn-hangzhou",
            bucket="test-bucket",
            access_key_id="fake",
            access_key_secret="fake",
        )
        with pytest.raises(ModuleNotFoundError, match="alibabacloud_oss_v2"):
            OSSRegistry.get_instance().register_from_config(config)

    def test_oss_client_wraps_adapter(self):
        mock = MockStorageAdapter()
        client = OSSClient(mock)
        assert client._adapter is mock
        assert hasattr(client, "upload_file")
        assert repr(client) == "OSSClient(MockStorageAdapter)"

    def test_oss_inject_injects_first_positional_arg(self):
        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        @oss_inject
        def do_upload(client, request: UploadRequest) -> UploadResult:
            return client.upload_file(request)

        request = UploadRequest(object_name="test.txt", file_path="/tmp/test.txt")
        result = do_upload(request)
        assert result.object_name == "test.txt"
        assert "upload_file:test.txt" in MockStorageAdapter._call_log

    def test_oss_inject_without_any_args(self):
        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        @oss_inject
        def do_get_meta(client, object_name: str) -> ObjectMetadata:
            return client.head_object(object_name)

        result = do_get_meta("test.txt")
        assert result.object_name == "test.txt"

    def test_oss_inject_passes_through_kwargs(self):
        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        @oss_inject
        def do_download(client, path: str, size: int) -> str:
            return f"{path}:{size}"

        result = do_download(path="/tmp/out.txt", size=2048)
        assert result == "/tmp/out.txt:2048"

    def test_oss_inject_unregistered_raises(self):
        OSSRegistry.get_instance().clear()

        @oss_inject
        def do_upload(client, request: UploadRequest) -> UploadResult:
            return client.upload_file(request)

        request = UploadRequest(object_name="test.txt", file_path="/tmp/test.txt")
        with pytest.raises(RuntimeError, match="OSS 适配器未注册"):
            do_upload(request)

    def test_oss_inject_auto_load_env_fails_without_sdk(self):
        OSSRegistry.get_instance().clear()
        os.environ.pop("OSS_ACCESS_KEY_ID", None)
        os.environ.pop("OSS_ACCESS_KEY_SECRET", None)
        os.environ.pop("OSS_REGION", None)
        os.environ.pop("OSS_BUCKET", None)

        @oss_inject
        def do_upload(client, request: UploadRequest) -> UploadResult:
            return client.upload_file(request)

        with pytest.raises(RuntimeError, match="OSS 适配器未注册"):
            do_upload(UploadRequest(object_name="x", file_path="/x"))

    def test_oss_injector_class(self):
        class TestUploader(OSSInjector[StorageService]):
            def upload(self, request: UploadRequest) -> UploadResult:
                return self._oss.upload_file(request)

            @property
            def _oss(self) -> StorageService:
                return self._resolve_oss()

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        uploader = TestUploader()
        result = uploader.upload(UploadRequest(object_name="x.txt", file_path="/x"))
        assert result.object_name == "x.txt"


class TestUploadService:
    """测试上传服务业务逻辑。"""

    def setup_method(self):
        OSSRegistry.get_instance().clear()
        MockStorageAdapter.reset_log()

    def teardown_method(self):
        OSSRegistry.get_instance().clear()

    def test_simple_upload_policy(self):
        from infrastructure.upload import UploadService, UploadPolicy, UploadError

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = UploadService()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"x" * 100)
            temp_path = f.name

        try:
            result = service.upload(temp_path, "small.txt", policy=UploadPolicy.SIMPLE)
            assert result.object_name == "small.txt"
            assert "upload_file:small.txt" in MockStorageAdapter._call_log
        finally:
            os.unlink(temp_path)

    def test_multipart_upload_policy(self):
        from infrastructure.upload import UploadService, UploadPolicy

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = UploadService()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"x" * 1024)
            temp_path = f.name

        try:
            result = service.upload(temp_path, "multi.bin", policy=UploadPolicy.MULTIPART)
            assert result.object_name == "multi.bin"
            assert "multipart_upload:multi.bin" in MockStorageAdapter._call_log
        finally:
            os.unlink(temp_path)

    def test_resumable_upload_policy(self):
        from infrastructure.upload import UploadService, UploadPolicy

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = UploadService()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as f:
            f.write(b"x" * 512)
            temp_path = f.name

        try:
            result = service.upload(temp_path, "resume.zip", policy=UploadPolicy.RESUMABLE)
            assert result.object_name == "resume.zip"
            assert "resumable_upload:resume.zip" in MockStorageAdapter._call_log
        finally:
            os.unlink(temp_path)

    def test_auto_policy_selects_simple_for_small_file(self):
        from infrastructure.upload import UploadService, UploadPolicy

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = UploadService(small_file_threshold=1024 * 1024)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"x" * 100)
            temp_path = f.name

        try:
            result = service.upload(temp_path, "auto_small.txt", policy=UploadPolicy.AUTO)
            assert "upload_file:auto_small.txt" in MockStorageAdapter._call_log
        finally:
            os.unlink(temp_path)

    def test_retry_on_failure(self):
        from infrastructure.upload import UploadService, UploadPolicy

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        MockStorageAdapter._fail_next = 2
        service = UploadService(max_retry_attempts=3, retry_base_delay=0.01)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test data")
            temp_path = f.name

        try:
            result = service.upload(temp_path, "retry.txt", policy=UploadPolicy.SIMPLE)
            assert result.object_name == "retry.txt"
            assert MockStorageAdapter._upload_count == 3
        finally:
            os.unlink(temp_path)
            MockStorageAdapter._fail_next = 0

    def test_upload_fails_after_max_retries(self):
        from infrastructure.upload import UploadService, UploadPolicy, UploadError

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        MockStorageAdapter._fail_next = 999
        service = UploadService(max_retry_attempts=3, retry_base_delay=0.001)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test")
            temp_path = f.name

        try:
            with pytest.raises(UploadError, match="已重试 3 次"):
                service.upload(temp_path, "fail.txt", policy=UploadPolicy.SIMPLE)
        finally:
            os.unlink(temp_path)
            MockStorageAdapter._fail_next = 0

    def test_upload_stream(self):
        from infrastructure.upload import UploadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = UploadService()
        stream = io.BytesIO(b"stream data here")

        result = service.upload_stream(stream, "stream.txt")
        assert result.object_name == "stream.txt"
        assert "upload_stream:stream.txt" in MockStorageAdapter._call_log

    def test_upload_nonexistent_file_raises(self):
        from infrastructure.upload import UploadService, UploadPolicy

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = UploadService()

        with pytest.raises(Exception, match="文件不存在"):
            service.upload("/nonexistent/path/xyz.txt", "xyz.txt", policy=UploadPolicy.SIMPLE)

    def test_batch_uploader(self):
        from infrastructure.upload import BatchUploader, UploadPolicy

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        batch = BatchUploader(max_retry_attempts=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            for i in range(3):
                p = Path(tmpdir) / f"file{i}.txt"
                p.write_bytes(b"data")
                files.append((str(p), f"obj{i}.txt"))

            results = batch.upload_batch(files, policy=UploadPolicy.SIMPLE)
            assert len(results) == 3
            for obj_name in results:
                assert isinstance(results[obj_name], UploadResult)
                assert "upload_file:" + obj_name in MockStorageAdapter._call_log


class TestDownloadService:
    """测试下载服务业务逻辑。"""

    def setup_method(self):
        OSSRegistry.get_instance().clear()
        MockStorageAdapter.reset_log()

    def teardown_method(self):
        OSSRegistry.get_instance().clear()

    def test_download_file(self):
        from infrastructure.download import DownloadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = DownloadService()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "downloaded.txt"
            result = service.download("remote.txt", target)
            assert result.object_name == "remote.txt"
            assert "download_file:remote.txt" in MockStorageAdapter._call_log

    def test_stream_download(self):
        from infrastructure.download import DownloadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = DownloadService()
        chunks = list(service.stream_download("large.bin", chunk_size=1024))
        assert chunks == [b"chunk1", b"chunk2"]
        assert "stream_download:large.bin" in MockStorageAdapter._call_log

    def test_signed_url_generation(self):
        from infrastructure.download import DownloadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = DownloadService()
        result = service.get_signed_url("private.pdf", expire_seconds=3600)

        assert result.object_name == "private.pdf"
        assert "signature=mock" in result.url
        assert result.method == "GET"
        assert "generate_signed_url:private.pdf" in MockStorageAdapter._call_log

    def test_signed_url_for_upload_method(self):
        from infrastructure.download import DownloadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = DownloadService()
        result = service.get_signed_url("upload-target.bin", expire_seconds=600, method="PUT")
        assert result.method == "PUT"
        assert "signature=mock" in result.url

    def test_object_exists_check(self):
        from infrastructure.download import DownloadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = DownloadService()
        assert service.check_object_exists("exists.txt") is True
        assert "head_object:exists.txt" in MockStorageAdapter._call_log

    def test_object_metadata_retrieval(self):
        from infrastructure.download import DownloadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        service = DownloadService()
        meta = service.get_object_metadata("meta.bin")
        assert meta.content_length == 2048
        assert "head_object:meta.bin" in MockStorageAdapter._call_log

    def test_progress_tracker(self):
        from infrastructure.download import DownloadProgressTracker

        tracker = DownloadProgressTracker(total_bytes=1000)
        tracker.update(300)
        downloaded, total = tracker.get_progress()
        assert downloaded == 300
        assert total == 1000


class TestModuleDecoupling:
    """验证模块解耦：替换底层实现不影响业务层。"""

    def setup_method(self):
        OSSRegistry.get_instance().clear()
        MockStorageAdapter.reset_log()

    def teardown_method(self):
        OSSRegistry.get_instance().clear()

    def test_switch_adapter_does_not_affect_service_code(self):
        from infrastructure.upload import UploadService, UploadPolicy
        from infrastructure.download import DownloadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        upload_svc = UploadService()
        download_svc = DownloadService()

        with tempfile.TemporaryDirectory() as tmpdir:
            up = Path(tmpdir) / "upload.txt"
            up.write_bytes(b"test")
            ur = upload_svc.upload(str(up), "decouple.txt", policy=UploadPolicy.SIMPLE)
            assert ur.object_name == "decouple.txt"

            dr = download_svc.download("remote.txt", Path(tmpdir) / "out.txt")
            assert dr.object_name == "remote.txt"

    def test_same_adapter_shared_across_services(self):
        from infrastructure.upload import UploadService
        from infrastructure.download import DownloadService

        mock = MockStorageAdapter()
        OSSRegistry.get_instance().register(mock)

        upload_svc = UploadService()
        download_svc = DownloadService()

        assert upload_svc._oss is download_svc._oss


class TestAliyunOSSAdapterInterface:
    """测试 AliyunOSSAdapter 对 StorageService 协议的实现。"""

    def test_adapter_has_all_protocol_methods(self):
        if AliyunOSSAdapter is None:
            pytest.skip("alibabacloud_oss_v2 SDK not installed")
        required = [
            "upload_file",
            "multipart_upload",
            "resumable_upload",
            "upload_stream",
            "download_file",
            "stream_download",
            "generate_signed_url",
            "head_object",
        ]
        for method in required:
            assert hasattr(AliyunOSSAdapter, method), f"缺少方法: {method}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    pytest.main([__file__, "-v", "--tb=short"])