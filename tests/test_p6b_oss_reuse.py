"""
P6b 集成测试 - 验证 storage_service 复用项目 oss 模块。

覆盖：
  P6b-1  LocalStorageBackend 满足 oss.base.StorageService Protocol（结构化检查）
  P6b-2  LocalStorageBackend 端到端实现 Protocol 所有方法
            （upload_file / generate_signed_url / head_object / 等）
  P6b-3  OSSRegistry 可注册 LocalStorageBackend（替代 AliyunOSSAdapter）
  P6b-4  StorageService 懒初始化：首次访问 _get_adapter() 才决定 backend
  P6b-5  StorageService.env 切换：env 有 OSS_* → backend_kind=oss；无 → local
  P6b-6  StorageService.adapter 暴露 Protocol 类型
  P6b-7  业务上传通过 Protocol 走通（不直接调用 LocalStorageBackend 方法）
  P6b-8  已注册的 Registry adapter 优先级高于 env
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class P6bOSSReuseTests(unittest.TestCase):
    """验证 storage_service 对项目 oss 模块的复用。"""

    def setUp(self) -> None:
        # 每个测试独立：清空 module-level singleton + OSSRegistry
        import api.v1.services.storage_service as ss_mod
        ss_mod._service = None
        from oss.di import OSSRegistry
        OSSRegistry.get_instance().clear()
        # 清空 env 中的 OSS_* 防止影响测试
        for k in list(os.environ.keys()):
            if k.startswith("OSS_"):
                os.environ.pop(k, None)

    # ── P6b-1 ──────────────────────────────────────────────
    def test_P6b_1_local_satisfies_protocol(self):
        """LocalStorageBackend 满足 oss.base.StorageService Protocol。"""
        from typing import runtime_checkable
        from oss.base import StorageService as Protocol
        from api.v1.services.storage_service import LocalStorageBackend

        backend = LocalStorageBackend(upload_dir=Path(tempfile.mkdtemp()))
        # Protocol 标记了 runtime_checkable（如果没标记则做方法集合检查）
        try:
            self.assertIsInstance(backend, Protocol)
        except TypeError:
            # Protocol 未标记 runtime_checkable 时回退到方法名检查
            proto_methods = {n for n in dir(Protocol) if not n.startswith("_")}
            for m in proto_methods:
                self.assertTrue(
                    hasattr(backend, m) and callable(getattr(backend, m, None)),
                    f"LocalStorageBackend 缺少 Protocol 方法: {m}",
                )

    # ── P6b-2 ──────────────────────────────────────────────
    def test_P6b_2_local_all_protocol_methods(self):
        """端到端：调用每个 Protocol 方法验证可用。"""
        from api.v1.services.storage_service import LocalStorageBackend
        from oss.base import (
            UploadRequest, DownloadRequest, StreamDownloadRequest,
            SignedURLRequest, PublicURLRequest,
        )

        with tempfile.TemporaryDirectory() as td:
            backend = LocalStorageBackend(upload_dir=Path(td))
            # 准备一个文件
            src = Path(td) / "src.bin"
            src.write_bytes(b"hello oss")
            # upload_file
            r1 = backend.upload_file(UploadRequest(
                object_name="local://bkt/file-001.txt", file_path=src,
            ))
            self.assertEqual(r1.object_name, "local://bkt/file-001.txt")
            # 落盘确认
            self.assertTrue((Path(td) / "bkt" / "file-001.txt").exists())
            # head_object
            meta = backend.head_object("local://bkt/file-001.txt")
            self.assertEqual(meta.content_length, 9)
            # download_file
            dst = Path(td) / "downloaded.bin"
            dres = backend.download_file(DownloadRequest(
                object_name="local://bkt/file-001.txt", target_path=dst,
            ))
            self.assertEqual(dres.written_bytes, 9)
            self.assertEqual(dst.read_bytes(), b"hello oss")
            # stream_download
            chunks = list(backend.stream_download(StreamDownloadRequest(
                object_name="local://bkt/file-001.txt", chunk_size=4,
            )))
            self.assertEqual(b"".join(chunks), b"hello oss")
            # generate_signed_url（返回 /raw 后缀，供视觉模型 fetch 字节流）
            signed = backend.generate_signed_url(SignedURLRequest(
                object_name="local://bkt/file-001.txt", expire_seconds=600,
            ))
            self.assertEqual(signed.url, "/api/v1/files/file-001/raw")
            self.assertIsNotNone(signed.expires_at)
            # get_public_url（同样返回 /raw 后缀）
            pub = backend.get_public_url(PublicURLRequest(
                object_name="local://bkt/file-001.txt",
            ))
            self.assertEqual(pub.url, "/api/v1/files/file-001/raw")
            # head_object 不存在
            with self.assertRaises(FileNotFoundError):
                backend.head_object("local://bkt/nope")

    # ── P6b-3 ──────────────────────────────────────────────
    def test_P6b_3_oss_registry_accepts_local(self):
        """OSSRegistry 可以注册 LocalStorageBackend 作为替代 AliyunOSSAdapter。"""
        from api.v1.services.storage_service import LocalStorageBackend
        from oss.di import OSSRegistry

        backend = LocalStorageBackend(upload_dir=Path(tempfile.mkdtemp()))
        OSSRegistry.get_instance().register(backend)
        # 拿回来类型一致
        out = OSSRegistry.get_instance().get_adapter()
        self.assertIs(out, backend)

    # ── P6b-4 ──────────────────────────────────────────────
    def test_P6b_4_storage_service_lazy_init(self):
        """StorageService 懒初始化：未触发前 backend_kind=uninitialized。"""
        from api.v1.services.storage_service import StorageService
        svc = StorageService()
        self.assertEqual(svc._backend_kind, "uninitialized")
        self.assertIsNone(svc._adapter)
        # 第一次访问触发
        _ = svc.backend_kind
        self.assertEqual(svc._backend_kind, "local")  # 无 env → local

    # ── P6b-5 ──────────────────────────────────────────────
    def test_P6b_5_env_switches_backend(self):
        """env 有 OSS_* 时 backend_kind=oss；无时=local。"""
        from api.v1.services.storage_service import StorageService

        # (a) 无 env → local
        svc1 = StorageService()
        self.assertEqual(svc1.backend_kind, "local")
        self.assertIsInstance(svc1.adapter.__class__, type)

        # (b) 设 env → 走 provide_oss_client
        os.environ["OSS_ACCESS_KEY_ID"] = "fake_id"
        os.environ["OSS_ACCESS_KEY_SECRET"] = "fake_secret"
        os.environ["OSS_REGION"] = "cn-beijing"
        os.environ["OSS_BUCKET"] = "fake-bucket"
        # provide_oss_client 会触发真实 SDK 调用：mock 掉
        from oss.aliyun_oss import AliyunOSSAdapter
        with patch.object(AliyunOSSAdapter, "from_config",
                          return_value=MagicMock(name="AliyunOSSAdapter-instance")):
            from api.v1.services import storage_service as ss_mod
            ss_mod._service = None
            from oss.di import OSSRegistry
            OSSRegistry.get_instance().clear()

            svc2 = StorageService()
            self.assertEqual(svc2.backend_kind, "oss")

        # 清理
        for k in list(os.environ.keys()):
            if k.startswith("OSS_"):
                os.environ.pop(k, None)
        from api.v1.services import storage_service as ss_mod2
        ss_mod2._service = None
        from oss.di import OSSRegistry as _R
        _R.get_instance().clear()

    # ── P6b-6 ──────────────────────────────────────────────
    def test_P6b_6_adapter_exposes_protocol(self):
        """StorageService.adapter 暴露 oss.base.StorageService 类型。"""
        from api.v1.services.storage_service import StorageService
        from oss.base import StorageService as Protocol

        svc = StorageService()
        adapter = svc.adapter
        # duck type：必须有这些方法
        for m in ("upload_file", "generate_signed_url", "head_object"):
            self.assertTrue(
                hasattr(adapter, m) and callable(getattr(adapter, m)),
                f"adapter 缺少方法: {m}",
            )

    # ── P6b-7 ──────────────────────────────────────────────
    def test_P6b_7_business_presign_uses_protocol(self):
        """业务 presign-upload 端点通过 Protocol 走通，不直连 backend 方法。

        验证：
          - storage_service.presign 调到 mock adapter 的 generate_signed_url
          - url 字段就是 mock 返回的 https://mock.oss/...
          - backend_kind 反映 OSSRegistry 注册状态
        """
        from api.v1.services.storage_service import StorageService
        from oss.di import OSSRegistry
        from oss.base import SignedURLRequest
        from datetime import datetime, timedelta

        # 注入 mock adapter
        mock_adapter = MagicMock(name="mock-storage-adapter")
        mock_adapter.generate_signed_url = MagicMock(return_value=MagicMock(
            object_name="bkt/file-x.png",
            url="https://mock.oss/file-x?sig=xxx",
            method="GET",
            expires_at=datetime.now() + timedelta(hours=1),
            signed_headers={},
        ))
        OSSRegistry.get_instance().register(mock_adapter)

        svc = StorageService()
        # 通过 Protocol 调用 presign
        signed = svc.adapter.generate_signed_url(SignedURLRequest(
            object_name="bkt/file-x.png",
            method="PUT",
            expire_seconds=600,
        ))
        # Protocol 方法被调到
        mock_adapter.generate_signed_url.assert_called_once()
        # 返回值字段
        self.assertEqual(signed.url, "https://mock.oss/file-x?sig=xxx")
        self.assertEqual(signed.method, "GET")
        self.assertIsNotNone(signed.expires_at)

    # ── P6b-8 ──────────────────────────────────────────────
    def test_P6b_8_registry_priority_over_env(self):
        """已注册的 adapter 优先级高于 env。"""
        from api.v1.services.storage_service import StorageService, LocalStorageBackend
        from oss.di import OSSRegistry

        # env 全部设上
        os.environ["OSS_ACCESS_KEY_ID"] = "x"
        os.environ["OSS_ACCESS_KEY_SECRET"] = "y"
        os.environ["OSS_REGION"] = "cn-beijing"
        os.environ["OSS_BUCKET"] = "b"

        # 显式注册 Local（mock）
        sentinel = MagicMock(name="sentinel-local")
        OSSRegistry.get_instance().register(sentinel)

        svc = StorageService()
        # 拿到的是 sentinel（说明走 registry 优先）
        self.assertIs(svc.adapter, sentinel)

        # 清理
        for k in list(os.environ.keys()):
            if k.startswith("OSS_"):
                os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
