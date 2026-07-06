"""
P6 集成测试 - OSS 直传组件（presign-upload 流程）

覆盖（新流程）：
  P6-1  POST /api/v1/oss/presign-upload 申请上传许可 → 拿 upload_url + public_url
  P6-2  PUT  /api/v1/oss/direct-upload/{file_id} 直传文件（LocalStorage 模式）
  P6-3  GET  /api/v1/files/{file_id}/raw 拿到文件字节流（视觉模型 fetch 用）
  P6-4  完整 e2e：presign → PUT → GET → 拿到完整文件字节
  P6-5  bucket 隔离：不同 bucket 的 object_name 不同
  P6-6  非法 file_id 拒绝（路径遍历防护）
  P6-7  GET  /api/v1/oss/health 存活 + backend 信息
  P6-8  e2e：presign-upload → 拿 public_url → 创建设计审查会话 → 拉详情
  P6-9  持久化：上传文件实际落盘到 uploads/{bucket}/，可被 GET raw 拿到
  P6-10 presign-upload 拒绝超大文件名（路径注入防护）
  P6-11 presign-upload 拒绝超短 ttl（<60s）
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


def _make_png(size_bytes: int = 256) -> bytes:
    """合法 PNG 头部 + padding。"""
    sig = b"\x89PNG\r\n\x1a\n"
    pad = b"\x00" * max(0, size_bytes - len(sig))
    return sig + pad


def _make_pdf(size_bytes: int = 1024) -> bytes:
    """合法 PDF 头部 + padding。"""
    head = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    pad = b"%pad\n" * ((size_bytes - len(head)) // 5)
    return head + pad + b"%%EOF"


def _presign(client, filename: str, content_type: str, bucket: str = "default", **kw) -> dict:
    """辅助：申请 presign + PUT 文件 + 返回 response body + 已上传的内容。"""
    body = {
        "bucket": bucket,
        "filename": filename,
        "content_type": content_type,
        "ttl_seconds": 600,
        **kw,
    }
    r = client.post("/api/v1/oss/presign-upload", json=body)
    return r


def _upload_via_presign(client, filename: str, content_type: str, payload: bytes, bucket: str = "default") -> tuple[dict, dict]:
    """完整 presign + PUT 直传流程，返回 (presign_body, put_body)。"""
    pr = _presign(client, filename, content_type, bucket)
    assert pr.status_code == 200, pr.text
    pb = pr.json()
    # 必须带 X-Nonce 防重放
    assert "nonce" in pb, f"presign 响应缺 nonce 字段: {pb}"
    rr = client.put(
        pb["upload_url"],
        headers={
            "x-oss-object-name": pb["object_name"],
            "x-nonce": pb["nonce"],
            "content-type": content_type,
        },
        content=payload,
    )
    assert rr.status_code == 200, rr.text
    return pb, rr.json()


class P6OSSUploadTests(unittest.TestCase):
    """后端 OSS presign-upload 集成测试。"""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app

        from api.v1.services import storage_service as ss
        ss._service = None  # 重建单例
        cls._client_ctx = TestClient(app)
        cls._client_ctx.__enter__()
        cls.client = cls._client_ctx

    @classmethod
    def tearDownClass(cls):
        cls._client_ctx.__exit__(None, None, None)

    def setUp(self) -> None:
        """每个 case 重置 storage_service + OSSRegistry + env。"""
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

    # ── P6-1 ────────────────────────────────────────────────
    def test_P6_1_presign_upload_returns_required_fields(self):
        """presign-upload 返回 upload_url + public_url + file_id + object_name + expires_at + backend。"""
        r = _presign(self.client, "proto.png", "image/png", "design-review-image")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # 必备字段
        for f in ("file_id", "object_name", "upload_url", "public_url", "expires_at", "storage_backend", "bucket", "nonce"):
            self.assertIn(f, body, f"missing {f} in {body}")
        # nonce 必须 32 字符 hex
        import re
        self.assertRegex(body["nonce"], r"^[a-f0-9]{32}$",
                         f"nonce 必须是 32 字符 hex: {body['nonce']}")
        # 必须是绝对 URL（含 scheme）
        self.assertTrue(body["upload_url"].startswith(("http://", "https://")),
                        f"upload_url 必须是绝对 URL: {body['upload_url']}")
        self.assertTrue(body["public_url"].startswith(("http://", "https://")),
                        f"public_url 必须是绝对 URL: {body['public_url']}")
        # upload_method 必须是 PUT
        self.assertEqual(body["upload_method"], "PUT")
        # object_name 格式（LocalStorage 模式）
        self.assertTrue(body["object_name"].startswith("local://design-review-image/"),
                        f"object_name 格式错误: {body['object_name']}")
        # file_id 格式
        self.assertRegex(body["file_id"], r"^file-[a-zA-Z0-9]+$")
        # expires_at 时间合法
        from datetime import datetime
        exp = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        self.assertGreater(exp.timestamp(), datetime.now().timestamp())

    # ── P6-2 ────────────────────────────────────────────────
    def test_P6_2_direct_upload_local_backend(self):
        """LocalStorage 模式下，PUT 到 upload_url 能写文件。"""
        content = _make_png(512)
        pb, put_body = _upload_via_presign(self.client, "proto.png", "image/png", content, "design-review-image")
        self.assertEqual(put_body["status"], "ok")
        self.assertEqual(put_body["file_id"], pb["file_id"])
        self.assertEqual(put_body["object_name"], pb["object_name"])

    # ── P6-3 ────────────────────────────────────────────────
    def test_P6_3_get_file_raw_returns_bytes(self):
        """GET public_url 拿到完整文件字节 + 正确 Content-Type。"""
        content = _make_png(384)
        pb, _ = _upload_via_presign(self.client, "raw.png", "image/png", content, "design-review-image")
        rr = self.client.get(pb["public_url"])
        self.assertEqual(rr.status_code, 200, rr.text)
        self.assertEqual(rr.content, content, "字节流必须与上传内容完全一致")
        self.assertTrue(
            rr.headers.get("content-type", "").startswith("image/png"),
            f"Content-Type 必须是 image/png: {rr.headers.get('content-type')}",
        )

    # ── P6-4 ────────────────────────────────────────────────
    def test_P6_4_full_e2e_presign_put_get(self):
        """完整端到端：presign → PUT → GET 字节一致。"""
        content = _make_pdf(2048)
        pb, _ = _upload_via_presign(self.client, "prd.pdf", "application/pdf", content, "design-review-prd")
        rr = self.client.get(pb["public_url"])
        self.assertEqual(rr.status_code, 200)
        self.assertEqual(rr.content, content)

    # ── P6-5 ────────────────────────────────────────────────
    def test_P6_5_bucket_isolation(self):
        """不同 bucket 的 object_name 不同，物理路径隔离。"""
        pb1, _ = _upload_via_presign(self.client, "a.png", "image/png", _make_png(64), "bucket-A")
        pb2, _ = _upload_via_presign(self.client, "a.png", "image/png", _make_png(64), "bucket-B")
        self.assertNotEqual(pb1["object_name"], pb2["object_name"])
        # 物理路径必须分别落在 uploads/bucket-A/ 和 uploads/bucket-B/
        # （LocalStorageBackend 的真实目录结构）
        self.assertIn("bucket-A", pb1["object_name"])
        self.assertIn("bucket-B", pb2["object_name"])

    # ── P6-6 ────────────────────────────────────────────────
    def test_P6_6_reject_invalid_file_id(self):
        """非法 file_id 在 PUT 阶段必须 400。"""
        for bad in ("../etc/passwd", "abc;rm", "file-with-space"):
            rr = self.client.put(
                f"/api/v1/oss/direct-upload/{bad}",
                headers={"x-oss-object-name": "local://default/x.png", "content-type": "image/png"},
                content=b"x",
            )
            self.assertIn(rr.status_code, (400, 404, 405),
                          f"非法 file_id={bad!r} 应被拒绝: {rr.status_code} {rr.text}")

    # ── P6-7 ────────────────────────────────────────────────
    def test_P6_7_health(self):
        r = self.client.get("/api/v1/oss/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn(body["backend"], ("local", "oss", "s3"))

    # ── P6-8 ────────────────────────────────────────────────
    def test_P6_8_e2e_public_url_into_design_review(self):
        """e2e：presign-upload → 拿 public_url → 创建设计审查会话 → 拉详情。

        验证 public_url（绝对 URL）能被设计审查接受，不引发 404。
        """
        # 1) 上传 PRD + 图片，拿到 public_url
        pdf_content = _make_pdf(1024)
        pdf_pb, _ = _upload_via_presign(self.client, "prd.pdf", "application/pdf", pdf_content, "design-review-prd")
        png_content = _make_png(256)
        png_pb, _ = _upload_via_presign(self.client, "proto.png", "image/png", png_content, "design-review-image")

        # 2) 创建设计审查会话（image_urls 用 public_url，不是 object_name）
        sess = self.client.post(
            "/api/v1/design-review/sessions",
            json={
                "user_id": "test-user",
                "prd_path": pdf_pb["public_url"],
                "image_urls": [png_pb["public_url"]],
            },
        )
        self.assertIn(sess.status_code, (200, 201),
                      f"create session failed: {sess.status_code} {sess.text}")
        body = sess.json()
        self.assertTrue(body.get("success"), f"响应 success=false: {body}")
        sid = body["session"]["dr_session_id"]

        # 3) 拉详情
        det = self.client.get(f"/api/v1/design-review/sessions/{sid}")
        self.assertEqual(det.status_code, 200)
        body = det.json()
        # image_urls 必须存的就是 public_url
        self.assertEqual(body["session"]["image_urls"], [png_pb["public_url"]])
        # 验证 public_url 真可访问（视觉模型能 fetch）
        rr = self.client.get(png_pb["public_url"])
        self.assertEqual(rr.status_code, 200)

    # ── P6-9 ────────────────────────────────────────────────
    def test_P6_9_actual_file_persisted(self):
        """上传文件实际落盘到 uploads/{bucket}/，且字节完全一致。"""
        content = _make_png(512)
        pb, _ = _upload_via_presign(self.client, "persisted.png", "image/png", content, "test-persist")
        # 从 object_name 解析物理路径
        rest = pb["object_name"][len("local://"):]
        bucket, saved_filename = rest.split("/", 1)
        file_path = Path("uploads") / bucket / saved_filename
        self.assertTrue(file_path.exists(), f"文件未落盘: {file_path}")
        self.assertEqual(file_path.read_bytes(), content)
        try:
            file_path.unlink()
        except OSError:
            pass

    # ── P6-10 ───────────────────────────────────────────────
    def test_P6_10_reject_path_traversal_in_filename(self):
        """presign-upload 拒绝路径注入 filename。"""
        for bad in ("../../../etc/passwd", "/etc/passwd", "..\\..\\evil.exe"):
            r = _presign(self.client, bad, "image/png", "default")
            # 应该 200 + 文件名被 sanitize（不再含 .. 或 /）
            if r.status_code == 200:
                body = r.json()
                self.assertNotIn("..", body["object_name"])
                self.assertFalse(body["object_name"].startswith("/"))

    # ── P6-11 ───────────────────────────────────────────────
    def test_P6_11_reject_short_ttl(self):
        """presign-upload 拒绝 ttl < 60s。"""
        r = self.client.post("/api/v1/oss/presign-upload", json={
            "bucket": "default",
            "filename": "x.png",
            "content_type": "image/png",
            "ttl_seconds": 10,
        })
        self.assertEqual(r.status_code, 422)  # Pydantic ge=60 校验失败

    # ── P6-12 ───────────────────────────────────────────────
    def test_P6_12_reject_oversize_direct_upload(self):
        """direct-upload 拒绝超大文件（>50MB）。"""
        pb = _presign(self.client, "big.png", "image/png", "default").json()
        # 构造 51MB 内容（流式上传）
        rr = self.client.put(
            pb["upload_url"],
            headers={
                "x-oss-object-name": pb["object_name"],
                "x-nonce": pb["nonce"],
                "content-type": "image/png",
            },
            content=b"\x00" * (51 * 1024 * 1024),
        )
        self.assertEqual(rr.status_code, 413, rr.text[:200])

    # ── P6-13: nonce 必备 ─────────────────────────────────────
    def test_P6_13_direct_upload_requires_nonce(self):
        """不带 X-Nonce 必须 400。"""
        pb = _presign(self.client, "x.png", "image/png", "default").json()
        rr = self.client.put(
            pb["upload_url"],
            headers={"x-oss-object-name": pb["object_name"], "content-type": "image/png"},
            content=b"fake",
        )
        self.assertEqual(rr.status_code, 400, rr.text)
        self.assertIn("X-Nonce", rr.text)

    # ── P6-14: nonce 二次消费被拒 ──────────────────────────────
    def test_P6_14_nonce_single_use(self):
        """同一个 nonce 第二次消费必须 409 NONCE_ALREADY_CONSUMED。"""
        pb = _presign(self.client, "x.png", "image/png", "default").json()
        # 第一次：成功
        r1 = self.client.put(
            pb["upload_url"],
            headers={
                "x-oss-object-name": pb["object_name"],
                "x-nonce": pb["nonce"],
                "content-type": "image/png",
            },
            content=b"first",
        )
        self.assertEqual(r1.status_code, 200, r1.text)
        # 第二次：必须 409（同一 nonce 重放）
        r2 = self.client.put(
            pb["upload_url"],
            headers={
                "x-oss-object-name": pb["object_name"],
                "x-nonce": pb["nonce"],
                "content-type": "image/png",
            },
            content=b"second",
        )
        self.assertEqual(r2.status_code, 409, r2.text)
        body = r2.json()
        self.assertEqual(body["detail"]["code"], "NONCE_ALREADY_CONSUMED")

    # ── P6-15: 伪造 nonce ─────────────────────────────────────
    def test_P6_15_forged_nonce_rejected(self):
        """伪造的 nonce 必须 403 NONCE_NOT_FOUND。"""
        pb = _presign(self.client, "x.png", "image/png", "default").json()
        # 32 字符 hex 但不在 store 里
        fake_nonce = "deadbeef" * 4  # 32 字符
        r = self.client.put(
            pb["upload_url"],
            headers={
                "x-oss-object-name": pb["object_name"],
                "x-nonce": fake_nonce,
                "content-type": "image/png",
            },
            content=b"x",
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["detail"]["code"], "NONCE_NOT_FOUND")

    # ── P6-16: 跨 file_id 滥用 nonce ─────────────────────────
    def test_P6_16_nonce_file_id_mismatch(self):
        """A 的 nonce 用到 B 的 file_id 必须 403 NONCE_FILE_MISMATCH。"""
        # 申请 A 的 presign
        pa = _presign(self.client, "a.png", "image/png", "default").json()
        # 申请 B 的 presign（不同 file_id）
        pb = _presign(self.client, "b.png", "image/png", "default").json()
        # 用 A 的 nonce 去 PUT 到 B 的 URL
        r = self.client.put(
            pb["upload_url"],
            headers={
                "x-oss-object-name": pb["object_name"],
                "x-nonce": pa["nonce"],
                "content-type": "image/png",
            },
            content=b"x",
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()["detail"]["code"], "NONCE_FILE_MISMATCH")

    # ── P6-17: 过期 nonce ─────────────────────────────────────
    def test_P6_17_expired_nonce_rejected(self):
        """过期 nonce 必须 409 NONCE_EXPIRED。"""
        import time
        from api.v1.services.nonce_store import get_nonce_store

        pb = _presign(self.client, "x.png", "image/png", "default").json()
        # 把 expires_at 改成过去
        store = get_nonce_store()
        store._conn()  # noop, just to ensure init
        with store._conn() as conn:
            conn.execute(
                "UPDATE upload_nonce SET expires_at = ? WHERE nonce = ?",
                (time.time() - 1, pb["nonce"]),
            )
        r = self.client.put(
            pb["upload_url"],
            headers={
                "x-oss-object-name": pb["object_name"],
                "x-nonce": pb["nonce"],
                "content-type": "image/png",
            },
            content=b"x",
        )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "NONCE_EXPIRED")

    # ── P6-18: 非法 nonce 格式 ────────────────────────────────
    def test_P6_18_invalid_nonce_format_rejected(self):
        """nonce 不是 32 字符 hex 必须 400（不用查表）。"""
        pb = _presign(self.client, "x.png", "image/png", "default").json()
        for bad in ("", "short", "a" * 33, "g" * 32, "0" * 32 + " "):
            r = self.client.put(
                pb["upload_url"],
                headers={
                    "x-oss-object-name": pb["object_name"],
                    "x-nonce": bad,
                    "content-type": "image/png",
                },
                content=b"x",
            )
            self.assertEqual(r.status_code, 400, f"bad nonce={bad!r}: {r.status_code} {r.text}")