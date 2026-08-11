"""
P6f 集成测试 - read_file/oss_adapter.py 接入项目 oss 模块（去 infrastructure 中转）。

覆盖：
  P6f-1  OSSFileIDAdapter 用 oss.Registry 注入的 StorageService 走通 upload_and_register
  P6f-2  OSSFileIDAdapter 用 Registry 注入的 StorageService 走通 get_signed_url
  P6f-3  显式传 storage_adapter 时优先级最高
  P6f-4  _FallbackLocalAdapter 满足 oss.base.StorageService Protocol
  P6f-5  兼容旧 API：upload_service / download_service property 不抛
  P6f-6  storage_adapter 缓存命中：dedup 跳过真实上传
  P6f-7  v1/v2 行为对齐：生成 object_name + 缓存 + 预签名 URL 链路一致
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class P6fReadFileOSSIntegrationTests(unittest.TestCase):
    """read_file/oss_adapter.py 接入 oss.Registry 后的契约。"""

    def setUp(self) -> None:
        for k in list(os.environ.keys()):
            if k.startswith("OSS_"):
                os.environ.pop(k, None)
        try:
            from oss.di import OSSRegistry
            OSSRegistry.get_instance().clear()
        except Exception:
            pass
        # 重置 read_file 模块级 adapter
        try:
            from agent.graphs.design_review.tools.read_file.oss_adapter import (
                reset_oss_file_id_adapter,
            )
            reset_oss_file_id_adapter()
        except Exception:
            pass

    def tearDown(self) -> None:
        for k in list(os.environ.keys()):
            if k.startswith("OSS_"):
                os.environ.pop(k, None)
        try:
            from oss.di import OSSRegistry
            OSSRegistry.get_instance().clear()
        except Exception:
            pass
        try:
            from agent.graphs.design_review.tools.read_file.oss_adapter import (
                reset_oss_file_id_adapter,
            )
            reset_oss_file_id_adapter()
        except Exception:
            pass

    def _make_mock_adapter(self):
        """构造一个满足 Protocol 的 mock。"""
        from oss.base import (
            UploadRequest, UploadResult,
            SignedURLRequest, SignedURLResult,
        )
        a = MagicMock(name="mock-storage")
        a.upload_file = MagicMock(return_value=UploadResult(
            object_name="local://bkt/abc.png", etag=None, version_id=None,
        ))
        a.generate_signed_url = MagicMock(return_value=SignedURLResult(
            object_name="local://bkt/abc.png",
            url="https://mock.oss/abc.png",
            method="GET",
            expires_at=None,
        ))
        return a

    # ── P6f-1 ──────────────────────────────────────────────
    def test_P6f_1_upload_uses_registry_adapter(self):
        from oss.di import OSSRegistry
        from agent.graphs.design_review.tools.read_file.oss_adapter import (
            OSSFileIDAdapter,
        )

        sentinel = self._make_mock_adapter()
        OSSRegistry.get_instance().register(sentinel)

        adapter = OSSFileIDAdapter()
        # 验证拿到的就是 sentinel
        self.assertIs(adapter.storage_adapter, sentinel)

        # 触发上传
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"hello world")
            tmp_path = f.name
        try:
            meta = asyncio.run(adapter.upload_and_register(
                file_path=tmp_path, object_name="local://bkt/test.txt",
                content_type="text/plain",
            ))
            sentinel.upload_file.assert_called_once()
            self.assertEqual(meta.object_name, "local://bkt/abc.png")  # mock 返回
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ── P6f-2 ──────────────────────────────────────────────
    def test_P6f_2_signed_url_uses_registry_adapter(self):
        from oss.di import OSSRegistry
        from agent.graphs.design_review.tools.read_file.oss_adapter import (
            OSSFileIDAdapter,
        )

        sentinel = self._make_mock_adapter()
        OSSRegistry.get_instance().register(sentinel)

        adapter = OSSFileIDAdapter()
        url = adapter.get_signed_url("local://bkt/abc.png", expire_seconds=600)
        sentinel.generate_signed_url.assert_called_once()
        self.assertEqual(url, "https://mock.oss/abc.png")

    # ── P6f-3 ──────────────────────────────────────────────
    def test_P6f_3_explicit_adapter_takes_priority(self):
        from oss.di import OSSRegistry
        from agent.graphs.design_review.tools.read_file.oss_adapter import (
            OSSFileIDAdapter,
        )

        registered = self._make_mock_adapter()
        explicit = self._make_mock_adapter()
        OSSRegistry.get_instance().register(registered)

        adapter = OSSFileIDAdapter(storage_adapter=explicit)
        self.assertIs(adapter.storage_adapter, explicit)

    # ── P6f-4 ──────────────────────────────────────────────
    def test_P6f_4_fallback_local_satisfies_protocol(self):
        from agent.graphs.design_review.tools.read_file.oss_adapter import (
            _FallbackLocalAdapter,
        )
        from oss.base import StorageService
        from typing import runtime_checkable

        local = _FallbackLocalAdapter(root=Path(tempfile.mkdtemp()))
        try:
            if hasattr(StorageService, "_is_runtime_protocol"):
                # Protocol 没标记 runtime_checkable → 用方法名兜底
                proto_methods = {n for n in dir(StorageService) if not n.startswith("_")}
                for m in proto_methods:
                    self.assertTrue(
                        hasattr(local, m) and callable(getattr(local, m, None)),
                        f"_FallbackLocalAdapter 缺方法: {m}",
                    )
            else:
                self.assertIsInstance(local, StorageService)
        except TypeError:
            # runtime_checkable 未标记：方法名检查
            for m in ("upload_file", "generate_signed_url", "head_object"):
                self.assertTrue(hasattr(local, m))

    # ── P6f-5 ──────────────────────────────────────────────
    def test_P6f_5_legacy_api_compat(self):
        """upload_service / download_service property 不抛（兼容旧代码）。"""
        from oss.di import OSSRegistry
        from agent.graphs.design_review.tools.read_file.oss_adapter import (
            OSSFileIDAdapter,
        )

        sentinel = self._make_mock_adapter()
        OSSRegistry.get_instance().register(sentinel)

        adapter = OSSFileIDAdapter()
        # 旧 API 返回 storage_adapter（duck-type 兼容）
        self.assertIs(adapter.upload_service, sentinel)
        self.assertIs(adapter.download_service, sentinel)

    # ── P6f-6 ──────────────────────────────────────────────
    def test_P6f_6_dedup_skips_real_upload(self):
        """缓存命中时不应调用 adapter.upload_file。"""
        from oss.di import OSSRegistry
        from agent.graphs.design_review.tools.read_file.oss_adapter import (
            OSSFileIDAdapter, FileMetadata,
        )
        from datetime import datetime

        sentinel = self._make_mock_adapter()
        OSSRegistry.get_instance().register(sentinel)

        adapter = OSSFileIDAdapter(enable_dedup=True)
        # 手动放入缓存
        cached_meta = FileMetadata(
            object_name="local://bkt/cached.txt",
            content_hash="abc123",
            content_length=10,
            content_type="text/plain",
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            access_count=1,
        )
        adapter._cache.put("local://bkt/cached.txt", cached_meta)

        # 上传：对象名已缓存 → 不调 upload_file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"hello")
            tmp_path = f.name
        try:
            meta = asyncio.run(adapter.upload_and_register(
                file_path=tmp_path, object_name="local://bkt/cached.txt",
            ))
            self.assertIs(meta, cached_meta)  # 返回缓存
            sentinel.upload_file.assert_not_called()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ── P6f-7 ──────────────────────────────────────────────
    def test_P6f_7_full_flow_consistent(self):
        """v1/v2 行为对齐：upload + signed_url + 多模态 dict。"""
        from oss.di import OSSRegistry
        from agent.graphs.design_review.tools.read_file.oss_adapter import (
            OSSFileIDAdapter,
        )

        sentinel = self._make_mock_adapter()
        OSSRegistry.get_instance().register(sentinel)

        adapter = OSSFileIDAdapter()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            tmp_path = f.name
        try:
            meta = asyncio.run(adapter.upload_and_register(
                file_path=tmp_path,
                object_name="local://bkt/proto.png",
                content_type="image/png",
            ))
            self.assertEqual(meta.object_name, "local://bkt/abc.png")
            # 拿 url
            url = adapter.get_signed_url(meta.object_name)
            self.assertEqual(url, "https://mock.oss/abc.png")
            # 多模态 dict
            mm = adapter.prepare_for_multimodal_model(meta.object_name, "vision")
            self.assertEqual(mm["type"], "image_url")
            self.assertEqual(mm["image_url"]["url"], "https://mock.oss/abc.png")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
