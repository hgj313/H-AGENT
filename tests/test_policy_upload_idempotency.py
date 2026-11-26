# -*- coding: utf-8 -*-
"""上传幂等自愈 单测（隔离：mock client，不接触真实飞书表）"""
import os
import sys
import tempfile
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from policy_analysis import import_local_pdfs as imp  # noqa: E402


class _FakeClient:
    """只实现 list_records / batch_create / batch_update / batch_delete

    按 table_id 分表返回：保险单表给 policy 记录，工人表给 worker 记录。
    """

    def __init__(self, policy_records: List[dict],
                 worker_records: List[dict] = None):
        self.policy_records = list(policy_records)
        self.worker_records = list(worker_records or [])
        self.created: List[dict] = []
        self.deleted: List[str] = []

    def get_token(self) -> str:
        return "fake_token"

    def list_records(self, table_id: str = "", page_size: int = 500,
                     **kw) -> List[dict]:
        from policy_analysis.config import INSURANCE_POLICY_TABLE
        if table_id == INSURANCE_POLICY_TABLE:
            return list(self.policy_records)
        return list(self.worker_records)

    def batch_create(self, records: List[dict], table_id: str = "") -> List[dict]:
        out = []
        for i, r in enumerate(records):
            rid = "recNEW%03d" % len(self.created)
            self.created.append(r)
            out.append({"record_id": rid, "id": rid, "fields": r.get("fields", {})})
        return out

    def batch_update(self, records: List[dict], table_id: str = "") -> List[dict]:
        return [{"record_id": r["record_id"], "id": r["record_id"]} for r in records]

    def batch_delete(self, record_ids: List[str], table_id: str = "") -> int:
        self.deleted.extend(record_ids)
        rs = set(record_ids)
        from policy_analysis.config import INSURANCE_POLICY_TABLE
        if table_id == INSURANCE_POLICY_TABLE:
            self.policy_records = [r for r in self.policy_records
                                   if r["record_id"] not in rs]
        else:
            self.worker_records = [r for r in self.worker_records
                                   if r["record_id"] not in rs]
        return len(record_ids)


class _FakeUploader:
    """替代真实上传器：不发 HTTP，直接返回确定性 token"""

    def __init__(self, client):
        self._client = client

    def upload(self, file_path: str, file_name: str = None, timeout: int = 300) -> str:
        import hashlib
        with open(file_path, "rb") as f:
            data = f.read()
        return "tk_up_" + hashlib.md5(data).hexdigest()[:12]


def _rec(rid: str, name: str, size: int) -> dict:
    return {
        "record_id": rid,
        "fields": {
            imp.F_ATTACHMENT: [{"file_token": "tk_" + rid, "name": name, "size": size}],
            imp.F_POLICY_NO: "MAIN-001",
        },
    }


class TestAttachmentIndex(unittest.TestCase):
    def test_index_maps_name_size_to_record_and_token(self):
        c = _FakeClient([
            _rec("recA", "a.pdf", 100),
            _rec("recB", "b.pdf", 200),
        ])
        idx = imp._build_attachment_index(c)
        self.assertEqual(idx[("a.pdf", 100)], ("recA", "tk_recA"))
        self.assertEqual(idx[("b.pdf", 200)], ("recB", "tk_recB"))
        self.assertEqual(len(idx), 2)

    def test_same_name_different_size_are_distinct(self):
        """同名但字节数不同 → 视为两个不同文件，不能误判为重复"""
        c = _FakeClient([_rec("recA", "x.pdf", 100), _rec("recB", "x.pdf", 999)])
        idx = imp._build_attachment_index(c)
        self.assertIn(("x.pdf", 100), idx)
        self.assertIn(("x.pdf", 999), idx)
        self.assertNotEqual(idx[("x.pdf", 100)], idx[("x.pdf", 999)])

    def test_dup_group_keeps_smallest_record_id(self):
        """表里已有同名同尺寸的两条（历史脏数据）→ 只索引 record_id 最小的一条
        （与清理脚本 dedup 语义一致：保留最早创建的）"""
        c = _FakeClient([_rec("recZZZ", "d.pdf", 50), _rec("recAAA", "d.pdf", 50)])
        idx = imp._build_attachment_index(c)
        self.assertEqual(idx[("d.pdf", 50)][0], "recAAA")

    def test_records_without_attachment_are_ignored(self):
        c = _FakeClient([{"record_id": "recX", "fields": {}}])
        self.assertEqual(len(imp._build_attachment_index(c)), 0)


class TestUploadIdempotency(unittest.TestCase):
    """跑真实的 stage_upload，用 mock client 验证「日志丢失也不重复创建」"""

    def _run(self, existing_records, files_spec, log_md5=None):
        tmpdir = tempfile.mkdtemp()
        # 造本地 PDF（字节数必须精确等于 files_spec 里的值）
        paths = {}
        header = b"%PDF-1.4 "
        for name in files_spec:
            p = os.path.join(tmpdir, name)
            size = files_spec[name]
            with open(p, "wb") as f:
                f.write(header + b"x" * (size - len(header)))
            assert os.path.getsize(p) == size, (name, os.path.getsize(p), size)
            paths[name] = p

        client = _FakeClient(existing_records)

        # 隔离缓存与日志文件
        imp.ANALYSIS_FILE = os.path.join(tmpdir, "analysis.json")
        imp.UPLOAD_LOG = os.path.join(tmpdir, "upload.json")
        cache = {"files": {}}
        missing = []
        for i, (name, size) in enumerate(files_spec.items()):
            md5 = "md5_%d" % i
            cache["files"][md5] = {
                "status": "ok",
                "result": {"main_policy_number": "M-%d" % i,
                           "batch_policy_number": "",
                           "policy_type": "主保单",
                           "insurance_company": "测试",
                           "persons": []},
            }
            missing.append({"md5": md5, "name": name, "path": paths[name]})

        # 预置日志：把第 1 个文件标记为「已上传」，其余留空
        pre_log = {"uploaded": [], "failed": [], "persons": {}}
        if log_md5 is not None:
            pre_log["uploaded"].append({"md5": log_md5, "name": list(files_spec)[0],
                                         "file_token": "tk_old", "record_id": "recOLD"})
        with open(imp.UPLOAD_LOG, "w", encoding="utf-8") as f:
            import json
            json.dump(pre_log, f)

        # 替换 client / uploader
        orig_client = imp._client
        imp._client = lambda: client
        import policy_analysis.feishu_uploader as fu
        orig_uploader = fu.AttachmentUploader
        fu.AttachmentUploader = _FakeUploader
        try:
            log = imp.stage_upload(missing, cache)
        finally:
            imp._client = orig_client
            fu.AttachmentUploader = orig_uploader
        return client, log

    def test_existing_attachment_is_reused_not_recreated(self):
        """核心场景：日志里没有该文件，但表里已有同名同尺寸附件
        → 必须复用已有记录，**不能再 batch_create**"""
        existing = [_rec("recEXIST", "policy.pdf", 100)]
        client, log = self._run(existing, {"policy.pdf": 100})
        self.assertEqual(len(client.created), 0, "不应新建记录")
        self.assertEqual(log["uploaded"][0]["record_id"], "recEXIST")
        self.assertEqual(log["uploaded"][0]["file_token"], "tk_recEXIST")

    def test_new_file_is_created(self):
        """表里没有 → 正常新建"""
        client, log = self._run([], {"new.pdf": 100})
        self.assertEqual(len(client.created), 1)
        self.assertEqual(log["uploaded"][0]["record_id"], "recNEW000")

    def test_log_hit_skips_creation(self):
        """日志里已有 → 走「已上传跳过」，不新建"""
        client, log = self._run([], {"policy.pdf": 100}, log_md5="md5_0")
        self.assertEqual(len(client.created), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
