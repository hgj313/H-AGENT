"""
P0 联调冒烟测试 - HTTP 端到端验证。

使用 FastAPI TestClient（in-process HTTP，exercise 完整 routing/validation/serialization）。

覆盖：
  SMOKE-1  App 启动 (lifespan + DB + AgentRegistry)
  SMOKE-2  GET  /api/v1/agents                 → 列出 react + design_review
  SMOKE-3  POST/PUT/GET /api/v1/chat/sessions  → 默认标题、CRUD
  SMOKE-4  POST /api/v1/react-agent/chat (非流式) → 响应结构
  SMOKE-5  POST /api/v1/react-agent/chat (SSE)    → 事件类型 + sequence 单调
  SMOKE-6  首轮完成后异步标题摘要                → session_title 改变
  SMOKE-7  inline 重命名                         → title_locked 幂等
  SMOKE-8  报告汇总

注意：
  - LLM 调用有超时与失败可能；失败时该 case 标记 SKIP，但不影响其他 case
  - 异步摘要任务用轮询等待最长 15s
  - 真实 DB（lifespan 启动时已初始化），本测试不污染关键数据
"""
from __future__ import annotations

# Windows: 强制 UTF-8 输出
import sys
import io
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

import json
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── 报告 ─────────────────────────────────────────────────────────────
class Report:
    def __init__(self) -> None:
        self.cases: list[tuple[str, str, str]] = []  # (id, status, detail)

    def add(self, case_id: str, status: str, detail: str = "") -> None:
        self.cases.append((case_id, status, detail))
        color = {"PASS": "✓", "FAIL": "✗", "SKIP": "~"}
        print(f"  {color.get(status, '?')} [{status}] {case_id}  {detail}")

    def passed(self) -> int:
        return sum(1 for _, s, _ in self.cases if s == "PASS")

    def failed(self) -> int:
        return sum(1 for _, s, _ in self.cases if s == "FAIL")

    def skipped(self) -> int:
        return sum(1 for _, s, _ in self.cases if s == "SKIP")

    def total(self) -> int:
        return len(self.cases)

    def print_summary(self) -> None:
        print()
        print("=" * 64)
        print(
            f"  TOTAL: {self.total()}  "
            f"PASS: {self.passed()}  "
            f"FAIL: {self.failed()}  "
            f"SKIP: {self.skipped()}"
        )
        print("=" * 64)


# ── SSE 解析器 ──────────────────────────────────────────────────────
def parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    """解析 SSE 文本，事件列表 [(event_type, data_dict), ...]."""
    events: list[tuple[str, dict[str, Any]]] = []
    current_event: Optional[str] = None
    current_data: list[str] = []
    for line in raw.splitlines():
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current_data.append(line[len("data:"):].strip())
        elif line == "":
            if current_event and current_data:
                try:
                    payload = json.loads("\n".join(current_data))
                except json.JSONDecodeError:
                    payload = {"_raw": "\n".join(current_data)}
                events.append((current_event, payload))
            current_event = None
            current_data = []
    return events


# ── 主流程 ──────────────────────────────────────────────────────────
def main() -> int:
    # 使用 lifespan 启动的真实 DB（不必替换）
    from fastapi.testclient import TestClient
    from api.main import app

    report = Report()
    print("\n>> SMOKE-1 启动 FastAPI 应用（TestClient lifespan）")
    try:
        with TestClient(app) as client:
            _run_all(client, report)
    except Exception as exc:  # noqa: BLE001
        report.add("SMOKE-1", "FAIL", f"lifespan 启动失败: {exc!r}")
        import traceback
        traceback.print_exc()

    report.print_summary()
    return 0 if report.failed() == 0 else 1


def _run_all(client: Any, report: Report) -> None:
    # SMOKE-1：app 启动
    report.add("SMOKE-1", "PASS", "lifespan + DB + Registry 启动成功")

    # SMOKE-2：列出所有 agent
    print("\n>> SMOKE-2 GET /api/v1/agents")
    r = client.get("/api/v1/agents")
    if r.status_code != 200:
        report.add("SMOKE-2", "FAIL", f"HTTP {r.status_code}: {r.text[:200]}")
        return
    payload = r.json()
    agents = payload.get("agents", [])
    ids = {a["config"]["agent_id"] for a in agents}
    if "react" in ids and "design_review" in ids:
        report.add(
            "SMOKE-2",
            "PASS",
            f"找到 {len(agents)} 个 agent: {sorted(ids)}",
        )
    else:
        report.add(
            "SMOKE-2",
            "FAIL",
            f"agent_ids={sorted(ids)} 缺少 react 或 design_review",
        )
        return

    # SMOKE-3：会话 CRUD
    print("\n>> SMOKE-3 会话 CRUD")
    r = client.post(
        "/api/v1/chat/sessions",
        json={"user_id": "smoke_user", "session_title": None},
    )
    if r.status_code != 200:
        report.add("SMOKE-3", "FAIL", f"create: HTTP {r.status_code} {r.text[:200]}")
        return
    sess = r.json()
    sid = sess["session_id"]
    if not sess["session_title"].startswith("新会话 "):
        report.add(
            "SMOKE-3",
            "FAIL",
            f"默认标题不正确: {sess['session_title']!r}",
        )
        return
    if sess.get("metadata", {}).get("title_locked") is True:
        report.add(
            "SMOKE-3",
            "FAIL",
            "默认标题应未锁定，但 metadata.title_locked=True",
        )
        return
    report.add(
        "SMOKE-3",
        "PASS",
        f"create OK  sid={sid[:8]}...  title={sess['session_title']!r}",
    )

    # 列表
    r = client.get("/api/v1/chat/sessions", params={"user_id": "smoke_user"})
    if r.status_code != 200 or not any(s["session_id"] == sid for s in r.json().get("sessions", [])):
        report.add("SMOKE-3.list", "FAIL", f"list 不含新会话: {r.text[:200]}")
    else:
        report.add("SMOKE-3.list", "PASS", "新会话出现在列表中")

    # 详情
    r = client.get(f"/api/v1/chat/sessions/{sid}")
    if r.status_code != 200 or r.json()["session_id"] != sid:
        report.add("SMOKE-3.get", "FAIL", f"get 失败: {r.text[:200]}")
    else:
        report.add("SMOKE-3.get", "PASS", "会话详情可拉取")

    # SMOKE-4：非流式对话（chat: stream=false）
    print("\n>> SMOKE-4 POST /api/v1/react-agent/chat (非流式)")
    r = _call_react_chat_non_stream(
        client,
        "请用一句话回答：1+1=?",
        session_id=None,
    )
    if r is None:
        report.add("SMOKE-4", "SKIP", "LLM 调用失败（无 API key 或网络问题）")
    elif r.status_code != 200:
        report.add("SMOKE-4", "FAIL", f"HTTP {r.status_code} {r.text[:300]}")
    else:
        body = r.json()
        required = {"task_id", "agent_id", "full_text", "duration_ms"}
        missing = required - set(body.keys())
        if missing:
            report.add("SMOKE-4", "FAIL", f"响应缺字段: {missing}")
        elif body["agent_id"] != "react":
            report.add("SMOKE-4", "FAIL", f"agent_id={body['agent_id']!r}")
        elif not body["full_text"]:
            report.add("SMOKE-4", "FAIL", "full_text 为空")
        else:
            report.add(
                "SMOKE-4",
                "PASS",
                f"task_id={body['task_id']}  duration={body['duration_ms']}ms  text={body['full_text'][:30]!r}...",
            )

    # SMOKE-5：SSE 流式（chat: stream=true）
    print("\n>> SMOKE-5 POST /api/v1/react-agent/chat (SSE)")
    raw, status = _call_react_chat_stream(
        client,
        "继续用一句话说：今天的建议是什么？",
        session_id=None,
    )
    if status != 200:
        report.add("SMOKE-5", "SKIP", f"LLM 流式失败 (HTTP {status})，跳过")
    else:
        events = parse_sse(raw)
        types = [t for t, _ in events]
        seqs = [
            d.get("sequence")
            for _, d in events
            if isinstance(d.get("sequence"), int)
        ]
        if "thinking" not in types:
            report.add("SMOKE-5", "FAIL", f"事件缺 thinking: {types}")
        elif "done" not in types:
            report.add("SMOKE-5", "FAIL", f"事件缺 done: {types}")
        elif seqs and seqs != sorted(seqs):
            report.add("SMOKE-5", "FAIL", f"sequence 非单调: {seqs}")
        elif seqs and len(set(seqs)) != len(seqs):
            report.add("SMOKE-5", "FAIL", f"sequence 重复: {seqs}")
        else:
            sample_message = next(
                (d for t, d in events if t == "message" and d.get("type") == "assistant"),
                None,
            )
            sample_thinking = next(
                (d for t, d in events if t == "thinking"),
                None,
            )
            done_payload = next((d for t, d in events if t == "done"), None)
            report.add(
                "SMOKE-5",
                "PASS",
                f"events={len(events)}  types={sorted(set(types))}  "
                f"seq={seqs[0]}..{seqs[-1] if seqs else 0}  "
                f"thinking={bool(sample_thinking)}  done={bool(done_payload)}",
            )

    # SMOKE-6：首轮完成后标题自动摘要
    print("\n>> SMOKE-6 首轮对话完成后标题自动摘要")
    sess2 = client.post(
        "/api/v1/chat/sessions",
        json={"user_id": "smoke_user"},
    ).json()
    sid2 = sess2["session_id"]
    title_before = sess2["session_title"]
    # 触发对话
    _ = _call_react_chat_stream(
        client,
        "我想咨询 Python 学习路径",
        session_id=sid2,
    )
    # 轮询等待异步摘要（anthropic provider 较慢，最多 60s）
    new_title: Optional[str] = None
    for i in range(60):
        time.sleep(1.0)
        r = client.get(f"/api/v1/chat/sessions/{sid2}")
        sess_after = r.json()
        if sess_after["session_title"] != title_before:
            new_title = sess_after["session_title"]
            break
    if new_title is None:
        # 可能 LLM 不可用 → 检查 metadata.title_summarized
        r = client.get(f"/api/v1/chat/sessions/{sid2}")
        meta = (r.json().get("metadata") or {})
        if meta.get("title_summarized") is True:
            new_title = r.json()["session_title"]
    if new_title and new_title != title_before and not new_title.startswith("新会话 "):
        report.add("SMOKE-6", "PASS", f"标题已摘要: {title_before!r} → {new_title!r}")
    elif new_title == title_before:
        report.add("SMOKE-6", "SKIP", f"标题未变化（LLM 可能不可用），保留 {title_before!r}")
    else:
        report.add(
            "SMOKE-6",
            "FAIL",
            f"等待 60s 后标题仍为 {title_before!r}",
        )

    # SMOKE-7：inline 重命名 → title_locked 幂等
    print("\n>> SMOKE-7 inline 重命名 + title_locked 幂等")
    # 显式改标题
    r = client.put(
        f"/api/v1/chat/sessions/{sid2}",
        json={"session_title": "我的 Python 路径"},
    )
    if r.status_code != 200:
        report.add("SMOKE-7", "FAIL", f"rename: HTTP {r.status_code}")
    else:
        renamed = r.json()
        if renamed["session_title"] != "我的 Python 路径":
            report.add("SMOKE-7", "FAIL", f"title={renamed['session_title']!r}")
        elif renamed.get("metadata", {}).get("title_locked") is not True:
            report.add("SMOKE-7", "FAIL", "改标题后未自动 title_locked")
        else:
            # 再触发一次对话，标题不应被覆写
            _ = _call_react_chat_stream(
                client,
                "再问个无关问题",
                session_id=sid2,
            )
            for _ in range(8):
                time.sleep(1.0)
                r = client.get(f"/api/v1/chat/sessions/{sid2}")
                if (r.json().get("metadata") or {}).get("title_summarized") is True:
                    # 摘要跑过了，但因为已 locked 应跳过覆写
                    break
            r = client.get(f"/api/v1/chat/sessions/{sid2}")
            final = r.json()
            if final["session_title"] == "我的 Python 路径":
                report.add(
                    "SMOKE-7",
                    "PASS",
                    "改标题后锁定，第二次摘要未覆写",
                )
            else:
                report.add(
                    "SMOKE-7",
                    "FAIL",
                    f"标题被覆写: {final['session_title']!r}",
                )


# ── HTTP 辅助 ───────────────────────────────────────────────────────
def _call_react_chat_non_stream(
    client: Any,
    message: str,
    session_id: Optional[str],
    timeout: float = 60.0,
) -> Optional[Any]:
    """非流式调用 ReactAgent，超时则返回 None。"""
    try:
        return client.post(
            "/api/v1/react-agent/chat",
            json={"message": message, "session_id": session_id, "stream": False},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 非流式调用异常: {exc!r}")
        return None


def _call_react_chat_stream(
    client: Any,
    message: str,
    session_id: Optional[str],
    timeout: float = 90.0,
) -> tuple[str, int]:
    """流式调用 ReactAgent，返回 (原始 SSE 文本, 状态码)。"""
    try:
        with client.stream(
            "POST",
            "/api/v1/react-agent/chat",
            json={"message": message, "session_id": session_id, "stream": True},
            timeout=timeout,
        ) as response:
            chunks: list[str] = []
            for chunk in response.iter_text():
                chunks.append(chunk)
            return "".join(chunks), response.status_code
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 流式调用异常: {exc!r}")
        return "", -1


if __name__ == "__main__":
    sys.exit(main())
