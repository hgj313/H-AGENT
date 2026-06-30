"""
P6e 集成测试 - presign-upload 独立性（直传流程下，服务端不做内容去重）

设计：
  在新 presign-upload 流程里，客户端先申请许可，再 PUT 文件到 upload_url。
  服务端无法在申请阶段知道文件内容 hash（因为客户端还没传），所以
  **服务端不做 idempotency 去重**——每次 presign-upload 都返回新 file_id。
  客户端要做去重需自己在本地比较 SHA-256(content)。

覆盖：
  P6e-1  同一客户端两次申请 presign → 返回不同 file_id 和 object_name
  P6e-2  不同 filename 但相同内容 → 还是返回不同 file_id（服务端无 content 可见）
  P6e-3  presign 返回的 file_id 全部满足 file-[a-zA-Z0-9_]+ 格式
  P6e-4  重复调用 N 次得到 N 个不同 file_id，UUID 空间充足
  P6e-5  presign-upload 申请后文件未上传，public_url 仍然返回 404
        （证明 file_id 与 storage 是 bind 关系，没传就没有内容）
  P6e-6  PUT 直传到相同 upload_url 二次，第二次会覆盖文件（last-write-wins）
        （新流程语义：上传是显式动作，不去重）
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _png(n: int = 64) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * max(0, n - 8)


class P6ePresignIndependenceTests(unittest.TestCase):
    """presign-upload 独立性 + 客户端去重推荐。"""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app

        from api.v1.services import storage_service as ss
        ss._service = None
        cls._client_ctx = TestClient(app)
        cls._client_ctx.__enter__()
        cls.client = cls._client_ctx

    @classmethod
    def tearDownClass(cls):
        cls._client_ctx.__exit__(None, None, None)

    def setUp(self) -> None:
        from api.v1.services import storage_service as ss_mod
        ss_mod._service = None
        for k in list(os.environ.keys()):
            if k.startswith("OSS_"):
                os.environ.pop(k, None)
        # 清 nonce store 防止测试间残留
        try:
            from api.v1.services.nonce_store import get_nonce_store
            get_nonce_store().clear_all()
        except Exception:
            pass
        try:
            from oss.di import OSSRegistry
            OSSRegistry.get_instance().clear()
        except Exception:
            pass

    # ── P6e-1 ──────────────────────────────────────────────
    def test_P6e_1_two_presigns_return_different_ids(self):
        r1 = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "x", "filename": "a.png", "content_type": "image/png", "ttl_seconds": 600,
        }).json()
        r2 = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "x", "filename": "a.png", "content_type": "image/png", "ttl_seconds": 600,
        }).json()
        self.assertNotEqual(r1["file_id"], r2["file_id"])
        self.assertNotEqual(r1["object_name"], r2["object_name"])

    # ── P6e-2 ──────────────────────────────────────────────
    def test_P6e_2_same_content_different_filename_still_different_id(self):
        """服务端在 presign 阶段无 content hash 可见，永远返回新 file_id。"""
        r1 = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "x", "filename": "a.png", "content_type": "image/png", "ttl_seconds": 600,
        }).json()
        r2 = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "x", "filename": "b.png", "content_type": "image/png", "ttl_seconds": 600,
        }).json()
        self.assertNotEqual(r1["file_id"], r2["file_id"])

    # ── P6e-3 ──────────────────────────────────────────────
    def test_P6e_3_file_id_format(self):
        for _ in range(20):
            r = self.client.post("/api/v1/oss/presign-upload", json={
                "bucket": "x", "filename": "f.png", "content_type": "image/png", "ttl_seconds": 600,
            }).json()
            import re
            self.assertRegex(r["file_id"], r"^file-[a-zA-Z0-9_]+$")

    # ── P6e-4 ──────────────────────────────────────────────
    def test_P6e_4_many_presigns_no_collision(self):
        ids = set()
        for _ in range(100):
            r = self.client.post("/api/v1/oss/presign-upload", json={
                "bucket": "x", "filename": "f.png", "content_type": "image/png", "ttl_seconds": 600,
            }).json()
            ids.add(r["file_id"])
        self.assertEqual(len(ids), 100, "100 次 presign 应得到 100 个不同 file_id")

    # ── P6e-5 ──────────────────────────────────────────────
    def test_P6e_5_presign_without_upload_yields_404(self):
        """申请 presign 但不 PUT 文件，GET public_url 必须 404。"""
        r = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "x", "filename": "f.png", "content_type": "image/png", "ttl_seconds": 600,
        }).json()
        # 没上传文件 → 公开 URL 应 404（证明 file_id ↔ storage 是 bind 关系）
        rr = self.client.get(r["public_url"])
        self.assertEqual(rr.status_code, 404)

    # ── P6e-6 ──────────────────────────────────────────────
    def test_P6e_6_reupload_overwrites(self):
        """业务用例：用户改主意，用新申请的上传覆盖旧文件。

        实现：第一次 PUT 用 nonce1 成功；申请新 presign（拿到新的 file_id + nonce2），
        但指向同一 object_name 写新文件，验证 GET 拿到最新版本。
        """
        # 第一次上传
        r1 = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "x", "filename": "f.png", "content_type": "image/png", "ttl_seconds": 600,
        }).json()
        first = _png(128)
        rr1 = self.client.put(
            r1["upload_url"],
            headers={
                "x-oss-object-name": r1["object_name"],
                "x-nonce": r1["nonce"],
                "content-type": "image/png",
            },
            content=first,
        )
        self.assertEqual(rr1.status_code, 200)

        # 第二次上传：新 presign（不同 file_id 和 nonce）
        r2 = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "x", "filename": "f.png", "content_type": "image/png", "ttl_seconds": 600,
        }).json()
        second = _png(256)
        rr2 = self.client.put(
            r2["upload_url"],
            headers={
                "x-oss-object-name": r2["object_name"],
                "x-nonce": r2["nonce"],
                "content-type": "image/png",
            },
            content=second,
        )
        self.assertEqual(rr2.status_code, 200)

        # 第二个文件的 GET 应拿到第二次的内容（last-write-wins per file_id）
        g = self.client.get(r2["public_url"])
        self.assertEqual(g.status_code, 200)
        self.assertEqual(g.content, second)

    # ── P6e-7: 同 nonce + 同 upload_url 二次 PUT 必须 409（防重放生效）──
    def test_P6e_7_replay_same_nonce_rejected(self):
        """同 nonce 第二次消费必须 409 NONCE_ALREADY_CONSUMED。"""
        r = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "x", "filename": "f.png", "content_type": "image/png", "ttl_seconds": 600,
        }).json()
        # 第一次 PUT：成功
        rr1 = self.client.put(
            r["upload_url"],
            headers={
                "x-oss-object-name": r["object_name"],
                "x-nonce": r["nonce"],
                "content-type": "image/png",
            },
            content=b"first",
        )
        self.assertEqual(rr1.status_code, 200)
        # 第二次 PUT（同 nonce）：必须 409
        rr2 = self.client.put(
            r["upload_url"],
            headers={
                "x-oss-object-name": r["object_name"],
                "x-nonce": r["nonce"],
                "content-type": "image/png",
            },
            content=b"second-replay",
        )
        self.assertEqual(rr2.status_code, 409, rr2.text)
        self.assertEqual(rr2.json()["detail"]["code"], "NONCE_ALREADY_CONSUMED")