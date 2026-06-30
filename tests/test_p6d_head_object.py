"""
P6d 集成测试 - GET /api/v1/oss/objects/{object_name} (head_object)。

覆盖：
  P6d-1  上传后查询：exists=True，content_length/file_size 一致
  P6d-2  查询不存在的对象：exists=False，200 业务化（不 404）
  P6d-3  object_name 含特殊字符（/ 斜杠）正常解析
  P6d-4  字段对齐 oss.base.ObjectMetadata（content_length / etag / metadata）
  P6d-5  backend 字段正确（local / oss）
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_pdf(size_bytes: int = 512) -> bytes:
    head = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    pad = b"%pad\n" * ((size_bytes - len(head)) // 5)
    return head + pad + b"%%EOF"


class P6dHeadObjectTests(unittest.TestCase):

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
        for k in list(os.environ.keys()):
            if k.startswith("OSS_"):
                os.environ.pop(k, None)
        from api.v1.services import storage_service as ss_mod
        ss_mod._service = None
        # 清 nonce store 防止上一个测试残留
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

    # ── P6d-1 ──────────────────────────────────────────────
    def test_P6d_1_head_after_upload(self):
        content = _make_pdf(1024)
        expected_size = len(content)  # 实际字节数（_make_pdf 加头尾）
        # 1) presign-upload
        pb = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "head-test",
            "filename": "doc.pdf",
            "content_type": "application/pdf",
            "ttl_seconds": 600,
        })
        self.assertEqual(pb.status_code, 200, pb.text)
        body_pb = pb.json()
        # 2) PUT 直传
        rr = self.client.put(
            body_pb["upload_url"],
            headers={
                "x-oss-object-name": body_pb["object_name"],
                "x-nonce": body_pb["nonce"],
                "content-type": "application/pdf",
            },
            content=content,
        )
        self.assertEqual(rr.status_code, 200, rr.text)
        obj = body_pb["object_name"]

        # 3) head_object 查询
        r2 = self.client.get(f"/api/v1/oss/objects/{obj}")
        self.assertEqual(r2.status_code, 200, r2.text)
        body = r2.json()
        self.assertTrue(body["exists"])
        self.assertEqual(body["object_name"], obj)
        self.assertEqual(body["content_length"], expected_size)
        self.assertEqual(body["backend"], "local")
        # metadata 至少是 dict
        self.assertIsInstance(body["metadata"], dict)

    # ── P6d-2 ──────────────────────────────────────────────
    def test_P6d_2_head_nonexistent(self):
        r = self.client.get("/api/v1/oss/objects/local://nope-bkt/never-existed.png")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["exists"])
        self.assertEqual(body["content_length"], None)

    # ── P6d-3 ──────────────────────────────────────────────
    def test_P6d_3_object_name_with_slash(self):
        """presign-upload 接受含 / 的 bucket；FastAPI path converter {object_name:path} 允许多段 /。"""
        content = _make_pdf(256)
        pb = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "with/slashes",
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "ttl_seconds": 600,
        }).json()
        rr = self.client.put(
            pb["upload_url"],
            headers={
                "x-oss-object-name": pb["object_name"],
                "x-nonce": pb["nonce"],
                "content-type": "application/pdf",
            },
            content=content,
        )
        self.assertEqual(rr.status_code, 200)
        obj = pb["object_name"]

        # FastAPI path converter {object_name:path} 允许多段 / 嵌套
        r2 = self.client.get(f"/api/v1/oss/objects/{obj}")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["exists"])

    # ── P6d-4 ──────────────────────────────────────────────
    def test_P6d_4_metadata_fields_aligned_to_protocol(self):
        """response 字段必须包含 oss.base.ObjectMetadata 全字段。"""
        from oss.base import ObjectMetadata
        from api.v1.schemas.oss import ObjectMetadataResponse

        proto_fields = {f.name for f in ObjectMetadata.__dataclass_fields__.values()}
        resp_fields = set(ObjectMetadataResponse.model_fields.keys())
        # 协议字段必须在响应 schema 中存在
        for f in proto_fields:
            self.assertIn(f, resp_fields, f"响应 schema 缺少 Protocol 字段: {f}")

    # ── P6d-5 ──────────────────────────────────────────────
    def test_P6d_5_backend_field_in_response(self):
        content = _make_pdf(128)
        pb = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "b-end",
            "filename": "x.pdf",
            "content_type": "application/pdf",
            "ttl_seconds": 600,
        }).json()
        rr = self.client.put(
            pb["upload_url"],
            headers={
                "x-oss-object-name": pb["object_name"],
                "x-nonce": pb["nonce"],
                "content-type": "application/pdf",
            },
            content=content,
        )
        self.assertEqual(rr.status_code, 200)
        obj = pb["object_name"]
        r2 = self.client.get(f"/api/v1/oss/objects/{obj}")
        body = r2.json()
        self.assertIn(body["backend"], ("local", "oss", "s3"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
