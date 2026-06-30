"""
Phase B 记忆/规划/执行 单测

不依赖真实 LLM 和真实 DuckDuckGo，使用 monkeypatch 注入 mock。

覆盖：
  L1  LongTermStore  add/search/get_all/count/去重
  L2  HistorySummarizer  is_important / partition
  L3  MemoryManager  build_context 装配（fact + summary + recent + important）
  L4  Planner  decide → react / plan
  L5  Executor  dispatch react / plan
  L6  web_search Tool  错误返回 + 成功返回
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── 共享 Mock LLM ───────────────────────────────────────────────────
class MockLLM:
    """最小可用 mock LLM：invoke 返回固定 content，stream 返回同内容。"""

    def __init__(self, content: str = "MOCK") -> None:
        self._content = content
        self.calls: list[list[Any]] = []

    def invoke(self, messages: list[Any], **_kw: Any) -> Any:
        self.calls.append(messages)
        m = MagicMock()
        m.content = self._content
        m.tool_calls = []
        return m

    async def ainvoke(self, messages: list[Any], **_kw: Any) -> Any:
        return self.invoke(messages, **_kw)

    def stream(self, messages: list[Any], **_kw: Any):  # noqa: ARG002
        m = MagicMock()
        m.content = self._content
        yield m


# ── L1: LongTermStore ───────────────────────────────────────────────
class TestLongTermStore(unittest.TestCase):
    def setUp(self) -> None:
        # 使用 tempfile.NamedTemporaryFile 避免 Windows 文件锁问题
        fd, path = tempfile.mkstemp(suffix=".db", prefix="test_lt_")
        os.close(fd)
        self.tmp = Path(path)
        from core.memory.long_term_store import LongTermStore

        self.LongTermStore = LongTermStore
        self.store = LongTermStore(db_path=self.tmp)

    def tearDown(self) -> None:
        # Windows 下 SQLite 可能短暂保留文件锁，重试几次
        for _ in range(3):
            try:
                if self.tmp.exists():
                    self.tmp.unlink()
                break
            except PermissionError:
                import time
                time.sleep(0.1)

    def test_add_and_search_substring(self) -> None:
        self.store.add_fact("u1", "用户名叫黄国俊", "identity")
        res = self.store.search("u1", "名字")
        self.assertEqual(len(res), 1)
        self.assertIn("黄国俊", res[0]["text"])

    def test_add_dedup(self) -> None:
        self.store.add_fact("u1", "用户名叫黄国俊")
        self.store.add_fact("u1", "用户名叫黄国俊")  # 重复
        self.assertEqual(self.store.count("u1"), 1)

    def test_bulk_add(self) -> None:
        n = self.store.add_facts_bulk(
            "u2",
            [
                {"text": "用户喜欢 Python", "category": "preference"},
                {"text": "用户住在上海", "category": "context"},
                {"text": "", "category": "other"},  # 空字符串应跳过
            ],
        )
        self.assertEqual(n, 2)
        self.assertEqual(self.store.count("u2"), 2)

    def test_search_user_isolation(self) -> None:
        self.store.add_fact("alice", "Alice 喜欢猫")
        self.store.add_fact("bob", "Bob 喜欢狗")
        self.assertEqual(self.store.search("alice", "猫")[0]["text"], "Alice 喜欢猫")
        self.assertEqual(len(self.store.search("bob", "猫")), 0)

    def test_get_all(self) -> None:
        for i in range(3):
            self.store.add_fact("u3", f"事实{i}")
        all_facts = self.store.get_all("u3")
        self.assertEqual(len(all_facts), 3)
        self.assertEqual(all_facts[0]["text"], "事实2")  # 倒序

    def test_search_limit(self) -> None:
        for i in range(10):
            self.store.add_fact("u4", f"用户喜欢{i}号")
        res = self.store.search("u4", "喜欢", limit=3)
        self.assertEqual(len(res), 3)


# ── L2: HistorySummarizer ───────────────────────────────────────────
class TestHistorySummarizer(unittest.TestCase):
    def test_is_important_keywords(self) -> None:
        from core.memory.summarizer import HistorySummarizer

        self.assertTrue(HistorySummarizer.is_important({"content": "我叫黄国俊", "role": "user"}))
        self.assertTrue(HistorySummarizer.is_important({"content": "我喜欢 Python", "role": "user"}))
        self.assertFalse(HistorySummarizer.is_important({"content": "今天天气不错", "role": "user"}))
        self.assertFalse(HistorySummarizer.is_important({"content": "你好", "role": "assistant"}))

    def test_is_important_tool(self) -> None:
        from core.memory.summarizer import HistorySummarizer

        self.assertTrue(HistorySummarizer.is_important({"content": "x", "role": "tool"}))
        self.assertTrue(HistorySummarizer.is_important({"content": "x", "message_type": "tool_call"}))

    def test_partition(self) -> None:
        from core.memory.summarizer import HistorySummarizer

        msgs = [
            {"role": "user", "content": "今天天气不错"},  # 普通
            {"role": "assistant", "content": "是挺好的"},
            {"role": "user", "content": "我叫张三"},  # 重要
            {"role": "assistant", "content": "记住了"},
        ]
        important, normal = HistorySummarizer.partition(msgs, k=0)
        # k=0 → 全部进入 important/normal 判定
        self.assertEqual(len(normal) + len(important), 4)
        self.assertTrue(any("张三" in m["content"] for m in important))
        self.assertTrue(any("天气" in m["content"] for m in normal))

    def test_summarize_with_mock(self) -> None:
        from core.memory.summarizer import HistorySummarizer

        summarizer = HistorySummarizer(MockLLM("用户叫张三，住在上海。"))
        out = summarizer.summarize(
            [{"role": "user", "content": "我叫张三，住在上海"}]
        )
        self.assertIn("张三", out)


# ── L3: MemoryManager.build_context ─────────────────────────────────
class TestMemoryManagerBuildContext(unittest.TestCase):
    def _build(self):
        # 临时 DB
        fd, path = tempfile.mkstemp(suffix=".db", prefix="test_lt_mm_")
        os.close(fd)
        self.tmp_lt = Path(path)
        from core.memory.long_term_store import LongTermStore
        from core.agents.memory_manager import MemoryManager

        long_term = LongTermStore(db_path=self.tmp_lt)
        # Mock MessageService / SessionService
        msg_svc = MagicMock()
        msg_svc.get_active_messages = MagicMock(return_value=[
            {"role": "user", "content": "最近 1", "message_type": "text"},
            {"role": "assistant", "content": "回答 1", "message_type": "text"},
        ])
        sess_svc = MagicMock()
        sess_svc.get_session = MagicMock(return_value={
            "metadata": {"history_summary": "用户之前问了 X"}
        })
        sess_svc.update_session = MagicMock()
        llm = MockLLM()
        mm = MemoryManager(llm, long_term, msg_svc, sess_svc, k=10)
        return mm, long_term, msg_svc, sess_svc

    def tearDown(self) -> None:
        # Windows 下 SQLite 文件锁可能延迟释放，跳过删除（tempfile 目录会自动清理）
        return

    def test_build_context_with_facts_and_summary(self) -> None:
        mm, lt, _, _ = self._build()
        lt.add_fact("u1", "用户名叫黄国俊", "identity")
        # query 与 fact 文本能匹配（关键词 "黄国俊" / "名字"）
        ctx = mm.build_context("s1", "u1", "黄国俊是谁？")
        # 第一条应为 system（含 facts + summary）
        from langchain_core.messages import SystemMessage

        self.assertIsInstance(ctx[0], SystemMessage)
        self.assertIn("黄国俊", ctx[0].content)
        self.assertIn("用户之前问了 X", ctx[0].content)  # summary
        # 末尾应为 HumanMessage("黄国俊是谁？")
        from langchain_core.messages import HumanMessage

        self.assertIsInstance(ctx[-1], HumanMessage)
        self.assertEqual(ctx[-1].content, "黄国俊是谁？")

    def test_build_context_recent_window(self) -> None:
        mm, lt, msg_svc, _ = self._build()
        # 构造 12 条消息，k=10，应保留 10 条
        msg_svc.get_active_messages = MagicMock(return_value=[
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}", "message_type": "text"}
            for i in range(12)
        ])
        ctx = mm.build_context("s1", "u1", "next")
        # 系统 + 10 条 recent + current = 12
        self.assertEqual(len(ctx), 12)

    def test_extract_and_store_facts(self) -> None:
        mm, lt, _, _ = self._build()
        # 替换 llm 让其返回带类别的事实
        mm.llm = MockLLM("[身份] 用户叫李四\n[偏好] 喜欢红色\n无")
        n = mm.extract_and_store_facts("s1", "u1", "我叫李四，我喜欢红色", "好的记住了")
        self.assertEqual(n, 2)
        facts = lt.get_all("u1")
        self.assertTrue(any("李四" in f["text"] for f in facts))


# ── L4: Planner.decide ──────────────────────────────────────────────
class TestPlanner(unittest.TestCase):
    def test_simple_chat_returns_react(self) -> None:
        from core.agents.planner import Planner

        p = Planner(MockLLM())
        import asyncio

        plan = asyncio.run(p.decide("你好", ""))
        self.assertEqual(plan["type"], "react")

    def test_keyword_hint_returns_plan(self) -> None:
        from core.agents.planner import Planner

        p = Planner(MockLLM())
        import asyncio

        plan = asyncio.run(p.decide("搜索 React 文档然后总结", ""))
        self.assertEqual(plan["type"], "plan")
        self.assertGreaterEqual(len(plan["steps"]), 1)


# ── L5: Executor dispatch ───────────────────────────────────────────
class TestExecutor(unittest.TestCase):
    def test_executor_react_mode(self) -> None:
        from core.agents.executor import Executor
        from core.agents.base import StreamEvent
        from api.v1.schemas.chat import StreamEventType

        async def fake_react(input_data):
            yield StreamEvent(
                event=StreamEventType.MESSAGE.value,
                data={"content": "hi", "type": "assistant", "partial": True},
                sequence=1,
                timestamp="2026-01-01",
                agent_id="react",
            )

        ex = Executor(fake_react)
        import asyncio

        events = []

        async def collect():
            async for evt in ex.run(
                {"type": "react", "goal": "x"},
                {"message": "m", "session_id": "s"},
                lambda: 1,
            ):
                events.append(evt)

        asyncio.run(collect())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, "message")

    def test_executor_plan_mode_runs_each_step(self) -> None:
        from core.agents.executor import Executor
        from core.agents.base import StreamEvent
        from api.v1.schemas.chat import StreamEventType

        async def fake_react(input_data):
            step = input_data.get("message", "")
            yield StreamEvent(
                event=StreamEventType.MESSAGE.value,
                data={"content": f"done:{step}", "type": "assistant", "partial": True},
                sequence=1,
                timestamp="2026-01-01",
                agent_id="react",
            )

        ex = Executor(fake_react)
        import asyncio

        events = []

        async def collect():
            async for evt in ex.run(
                {"type": "plan", "steps": ["step1", "step2"]},
                {"message": "ignored", "session_id": "s"},
                lambda: 1,
            ):
                events.append(evt)

        asyncio.run(collect())
        # 1 thinking + 2*(1 node_update + 1 message) + 1 done = 6
        self.assertGreaterEqual(len(events), 5)
        last = events[-1]
        self.assertEqual(last.event, "done")
        self.assertIn("step1", last.data["full_text"])
        self.assertIn("step2", last.data["full_text"])


# ── L6: web_search Tool ─────────────────────────────────────────────
class TestWebSearchTool(unittest.TestCase):
    def test_returns_error_when_query_empty(self) -> None:
        from core.agents.tools.search_tool import web_search

        out = web_search.invoke({"query": "", "max_results": 5})
        self.assertIn("ERROR", out)

    def test_returns_error_when_ddg_not_available(self) -> None:
        from core.agents.tools import search_tool as st

        with patch.object(st, "_do_search", return_value=[]):
            from core.agents.tools.search_tool import web_search

            out = web_search.invoke({"query": "test", "max_results": 5})
        self.assertIn("ERROR", out)

    def test_returns_results_on_success(self) -> None:
        from core.agents.tools import search_tool as st

        fake = [
            {"title": "T", "snippet": "S", "url": "http://x"},
            {"title": "T2", "snippet": "S2", "url": "http://y"},
        ]
        with patch.object(st, "_do_search", return_value=fake):
            from core.agents.tools.search_tool import web_search

            out = web_search.invoke({"query": "test", "max_results": 5})
        data = json.loads(out)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["title"], "T")


if __name__ == "__main__":
    unittest.main(verbosity=2)
