"""
P4 集成测试 - design_review 端点 + 持久化 + 报告拉取。

覆盖：
  P4-1  POST /api/v1/design-review/sessions              创建会话
  P4-2  GET  /api/v1/design-review/sessions              列出
  P4-3  GET  /api/v1/design-review/sessions/{id}         详情
  P4-4  POST /api/v1/design-review/sessions/{id}/run     流式 + 报告落库
  P4-5  GET  /api/v1/design-review/reports/{rid}         按报告 ID 拉
  P4-6  GET  /api/v1/design-review/sessions/{id}/report  按会话拉最新
  P4-7  报告 status 流转：pending → running → completed/failed
  P4-8  session_id 校验：未知 id 返回 404
"""
from __future__ import annotations

import json
import sys
import time
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    cur_event: str | None = None
    cur_data: list[str] = []
    for line in raw.splitlines():
        if line.startswith("event:"):
            cur_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            cur_data.append(line[len("data:"):].strip())
        elif line == "":
            if cur_event and cur_data:
                try:
                    payload = json.loads("\n".join(cur_data))
                except json.JSONDecodeError:
                    payload = {"_raw": "\n".join(cur_data)}
                out.append((cur_event, payload))
            cur_event = None
            cur_data = []
    return out


class P4DesignReviewE2ETests(unittest.TestCase):
    """使用 FastAPI TestClient + mock DesignReviewAgent.execute()。"""

    def setUp(self) -> None:
        # 在 import app 前 patch 掉 design_review_agent 的 execute，
        # 避免真实 LLM 加载
        from fastapi.testclient import TestClient
        from api.main import app
        from api.v1.endpoints import design_review as dr_endpoint
        from api.v1.services import design_review_service as dr_svc
        from core.registry.agent_registry import AgentRegistry

        # 真实持久化：用 tempfile db
        import tempfile, os
        import api.v1.services.design_review_service as dr_svc_mod
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._tmp_db = Path(path)
        # 重置 schema 初始化标志，让新 service 用新 db_path 重建
        dr_svc_mod._initialized = False
        dr_svc_mod.DB_PATH = self._tmp_db
        dr_endpoint._service = None
        # 直接 patch _get_service：永远基于当前 _tmp_db 返回新实例
        from api.v1.services.design_review_service import DesignReviewService
        self._get_svc_patch = patch.object(
            dr_endpoint, "_get_service",
            lambda: DesignReviewService(db_path=self._tmp_db),
        )
        self._get_svc_patch.start()
        self.addCleanup(self._get_svc_patch.stop)

        # 真实 PRD 文件（API 层 _resolve_drs_input 会读它）
        self._tmp_prd = self._tmp_db.parent / f"prd-{uuid.uuid4().hex[:6]}.md"
        self._tmp_prd.write_text(
            "# Mock PRD\n\n## 颜色/主色\n值: #1b2338\n## 字体/正文字体\n值: PingFang SC\n",
            encoding="utf-8",
        )
        self.addCleanup(lambda: self._tmp_prd.unlink(missing_ok=True))
        # 真实公网图片 URL（mock 视觉模型不真 fetch，只验透传）
        self._mock_image_url = "https://example.com/mock.png"

        # Mock agent.execute() 流出真实可用的事件
        from api.v1.schemas.chat import StreamEvent, StreamEventType
        from datetime import datetime

        async def fake_execute(self, input_data, task_id=None):
            from datetime import datetime as _dt
            seq = 0
            def _e(t, d):
                nonlocal seq
                seq += 1
                return StreamEvent(
                    event=t.value,
                    data=d,
                    agent_id="design_review",
                    timestamp=_dt.now(),
                    sequence=seq,
                )
            yield _e(StreamEventType.THINKING, {"stage": "start"})
            yield _e(
                StreamEventType.MESSAGE,
                {
                    "content": "设计审查完成！报告已生成。",
                    "type": "report",
                    "report_data": {
                        "meta": {
                            "report_id": "DR-TEST",
                            "generated_at": "2026-06-09T22:00:00",
                            "prd_source": input_data.get("file_paths", [""])[0],
                            "prototype_source": str(input_data.get("image_urls", [])),
                            "total_items": 1,
                            "compliance_rate": 0.5,
                        },
                        "summary": {
                            "by_outcome": {"pass": 1, "deviation": 0, "violation": 0, "missing": 0, "unspecified": 0, "prd_override": 0},
                            "by_severity": {"critical": 0, "major": 0, "minor": 0, "info": 1},
                            "by_category": {},
                        },
                        "items": [
                            {
                                "item_id": "X-1",
                                "dimension_key": "color.primary",
                                "category": "color",
                                "context": "primary color",
                                "standard": {"value": "#000", "raw_value": "#000", "is_mandatory": True, "severity": "info", "is_unspecified": False},
                                "prd": {"value": "#000", "exists": True, "matches_standard": True},
                                "prototype": {"value": "#000", "exists": True, "matches_standard": True},
                                "outcome": "pass",
                                "severity": "info",
                                "diff_summary": "ok",
                                "suggestion": "",
                                "expected_value": "#000",
                                "is_strong_violation": False,
                            }
                        ],
                        "top_issues": [],
                        "action_items": [],
                        "charts": {},
                    },
                },
            )
            yield _e(
                StreamEventType.DONE,
                {"task_id": "t1", "report_id": "DR-TEST", "duration_ms": 100, "agent_id": "design_review"},
            )

        # patch BaseAgent.execute
        from core.agents.design_review_agent import DesignReviewAgent
        self._patch = patch.object(DesignReviewAgent, "execute", fake_execute)
        self._patch.start()
        self.addCleanup(self._patch.stop)

        # 进入 lifespan 启动（registry 才会挂到 app.state）
        self._client_ctx = TestClient(app)
        self._client_ctx.__enter__()
        self.addCleanup(self._client_ctx.__exit__, None, None, None)
        self._client = self._client_ctx

    def tearDown(self) -> None:
        try:
            self._tmp_db.unlink()
        except Exception:  # noqa: BLE001
            pass

    def test_P4_1_create_session(self):
        r = self._client.post(
            "/api/v1/design-review/sessions",
            json={
                "user_id": "u1",
                "prd_path": str(self._tmp_prd),
                "image_urls": ["https://x/a.png"],
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data.get("success"))
        sid = data["session"]["dr_session_id"]
        self.assertTrue(sid.startswith("dr-"))

    def test_P4_2_list_sessions(self):
        # 先建 2 个
        self._client.post(
            "/api/v1/design-review/sessions",
            json={"user_id": "u1", "prd_path": str(self._tmp_prd)},
        )
        self._client.post(
            "/api/v1/design-review/sessions",
            json={"user_id": "u1", "prd_path": str(self._tmp_prd), "image_urls": [self._mock_image_url]},
        )
        r = self._client.get("/api/v1/design-review/sessions?user_id=u1")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["success"], True)
        self.assertGreaterEqual(len(data["sessions"]), 2)

    def test_P4_3_get_session_detail(self):
        c = self._client.post(
            "/api/v1/design-review/sessions",
            json={"user_id": "u1", "prd_path": str(self._tmp_prd)},
        ).json()
        sid = c["session"]["dr_session_id"]
        r = self._client.get(f"/api/v1/design-review/sessions/{sid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["session"]["dr_session_id"], sid)

    def test_P4_4_run_and_save_report(self):
        c = self._client.post(
            "/api/v1/design-review/sessions",
            json={"user_id": "u1", "prd_path": str(self._tmp_prd), "image_urls": [self._mock_image_url]},
        ).json()
        sid = c["session"]["dr_session_id"]

        with self._client.stream(
            "POST",
            f"/api/v1/design-review/sessions/{sid}/run",
            json={"message": ""},
        ) as r:
            self.assertEqual(r.status_code, 200)
            raw = "".join(r.iter_text())

        events = _parse_sse(raw)
        types = [t for t, _ in events]
        self.assertIn("done", types)
        # 流中应含 report 类型的 message
        report_msgs = [
            d
            for t, d in events
            if t == "message" and (d.get("data") or {}).get("type") == "report"
        ]
        self.assertGreaterEqual(len(report_msgs), 1)

    def test_P4_5_get_report_by_id_after_run(self):
        c = self._client.post(
            "/api/v1/design-review/sessions",
            json={"user_id": "u1", "prd_path": str(self._tmp_prd), "image_urls": [self._mock_image_url]},
        ).json()
        sid = c["session"]["dr_session_id"]

        with self._client.stream(
            "POST", f"/api/v1/design-review/sessions/{sid}/run", json={}
        ) as r:
            raw = "".join(r.iter_text())

        # 拿 session 应有 report_id
        sess = self._client.get(f"/api/v1/design-review/sessions/{sid}").json()["session"]
        rid = sess.get("report_id")
        self.assertTrue(rid, f"session 应有 report_id，实际: {sess}")
        # 拉报告
        r = self._client.get(f"/api/v1/design-review/reports/{rid}")
        self.assertEqual(r.status_code, 200)
        rep = r.json()["report"]
        self.assertEqual(rep["status"], "completed")
        self.assertIn("report_data", rep)

    def test_P4_6_get_latest_report_by_session(self):
        c = self._client.post(
            "/api/v1/design-review/sessions",
            json={"user_id": "u1", "prd_path": str(self._tmp_prd), "image_urls": [self._mock_image_url]},
        ).json()
        sid = c["session"]["dr_session_id"]
        with self._client.stream(
            "POST", f"/api/v1/design-review/sessions/{sid}/run", json={}
        ) as r:
            "".join(r.iter_text())
        r = self._client.get(f"/api/v1/design-review/sessions/{sid}/report")
        self.assertEqual(r.status_code, 200)
        rep = r.json()["report"]
        self.assertEqual(rep["dr_session_id"], sid)
        self.assertIn("report_data", rep)

    def test_P4_7_status_transition(self):
        c = self._client.post(
            "/api/v1/design-review/sessions",
            json={"user_id": "u1", "prd_path": str(self._tmp_prd)},
        ).json()
        sid = c["session"]["dr_session_id"]
        # 初始 pending
        self.assertEqual(
            self._client.get(f"/api/v1/design-review/sessions/{sid}").json()["session"]["status"],
            "pending",
        )
        with self._client.stream(
            "POST", f"/api/v1/design-review/sessions/{sid}/run", json={}
        ) as r:
            "".join(r.iter_text())
        # 完成后应 completed
        self.assertEqual(
            self._client.get(f"/api/v1/design-review/sessions/{sid}").json()["session"]["status"],
            "completed",
        )

    def test_P4_8_unknown_session_404(self):
        r = self._client.get("/api/v1/design-review/sessions/dr-nope")
        self.assertEqual(r.status_code, 404)
        r = self._client.get("/api/v1/design-review/sessions/dr-nope/report")
        self.assertEqual(r.status_code, 404)
        r = self._client.get("/api/v1/design-review/reports/DR-NOPE")
        self.assertEqual(r.status_code, 404)

    def test_P4_9_hard_fail_when_prd_path_unresolvable(self):
        """用户显式提供了 prd_path 但文件不存在 → 必须硬失败，绝不能静默吞错跑出假成功。"""
        c = self._client.post(
            "/api/v1/design-review/sessions",
            json={"user_id": "u1", "prd_path": "this-file-does-not-exist.md"},
        ).json()
        sid = c["session"]["dr_session_id"]

        # 跑审查
        with self._client.stream(
            "POST", f"/api/v1/design-review/sessions/{sid}/run", json={}
        ) as r:
            raw = "".join(r.iter_text())
        events = _parse_sse(raw)

        # 1) 流中必须有 error 事件（透传给前端，绝不吞错）
        error_events = [d for t, d in events if t == "error"]
        self.assertGreaterEqual(
            len(error_events), 1,
            f"硬失败必须发 error 事件，实际流: {[t for t, _ in events]}",
        )
        self.assertEqual(
            error_events[0]["data"]["code"], "INPUT_RESOLVE_FAILED",
        )
        # 2) 流中也必须有 done 事件（让前端能正常关闭流）
        done_events = [d for t, d in events if t == "done"]
        self.assertGreaterEqual(len(done_events), 1)
        self.assertEqual(done_events[0]["data"]["status"], "failed")

        # 3) session.status 必须为 failed，不能是 completed
        sess = self._client.get(
            f"/api/v1/design-review/sessions/{sid}"
        ).json()["session"]
        self.assertEqual(sess["status"], "failed")
        # 4) 必须有 error 字段说明失败原因
        self.assertIn("PRD 文件不存在", sess.get("error", ""))
        # 5) 必须没有 report_id（agent 没跑过，没产生报告）
        self.assertIsNone(sess.get("report_id"))

    def test_P4_10_public_image_url_passthrough(self):
        """公网 https:// 图片 URL 直接透传给 agent，不做 base64/data URI 转换。

        验证方式：构造一个 run 端点的小型 endpoint 单元测试，
        直接调用 _resolve_drs_input，验证输出 image_urls 字段等于入参。
        （端到端 agent.execute 的 patch 太复杂，契约已经在 _resolve_drs_input 处收敛。）
        """
        from api.v1.endpoints.design_review import _resolve_drs_input
        resolved = _resolve_drs_input({
            "prd_path": str(self._tmp_prd),
            "image_urls": [self._mock_image_url, "https://x.example.com/a.png"],
        })
        self.assertEqual(
            resolved["image_urls"],
            [self._mock_image_url, "https://x.example.com/a.png"],
            "公网 URL 必须原样透传，不做 base64/data URI 转换",
        )
        self.assertNotIn(
            "data:", "".join(resolved["image_urls"]),
            "绝对不允许出现 data URI（视觉模型 fetch 不友好）",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
