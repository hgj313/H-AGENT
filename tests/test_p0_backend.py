"""
P0 后端冒烟测试。

覆盖：
- StreamEvent 增加 sequence 字段
- ReactAgent 配置/校验/导入
- build_react_graph 最小可执行
- SessionService 默认标题格式与 _is_default_title 判定
- SessionService.update_session 自动 title_locked
- SessionService.summarize_and_update_title 幂等性（无 LLM 路径）

不依赖真实 LLM 也不依赖真实数据库，使用临时 SQLite。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


# ── 让 tests/ 目录可发现项目根 ──────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── 测试：StreamEvent sequence 字段 ─────────────────────────────────
class TestStreamEventSequence(unittest.TestCase):
    def test_dataclass_has_sequence(self) -> None:
        from core.agents.base import StreamEvent
        evt = StreamEvent(event="message", data={"x": 1}, sequence=7)
        self.assertEqual(evt.sequence, 7)

    def test_sse_payload_contains_sequence(self) -> None:
        from core.agents.base import StreamEvent
        evt = StreamEvent(event="done", data={"k": "v"}, sequence=42)
        sse = evt.to_sse_format()
        # 关键字段都在 data JSON 中
        self.assertIn('"sequence": 42', sse)
        self.assertIn('"k": "v"', sse)
        self.assertIn('event: done', sse)

    def test_pydantic_schema_has_sequence(self) -> None:
        from api.v1.schemas.chat import StreamEvent
        evt = StreamEvent(event="message", data={"x": 1}, sequence=3)
        self.assertEqual(evt.sequence, 3)
        sse = evt.to_sse_format()
        self.assertIn('"sequence": 3', sse)


# ── 测试：ReactAgent 导入与配置 ────────────────────────────────────
class TestReactAgentImport(unittest.TestCase):
    def test_import(self) -> None:
        from core.agents.react_agent import (
            ReactAgent,
            ReactState,
            build_react_graph,
            default_react_tools,
            register_react_agent,
        )
        self.assertTrue(callable(build_react_graph))
        self.assertTrue(callable(register_react_agent))

    def test_config(self) -> None:
        from core.agents.react_agent import ReactAgent
        agent = ReactAgent()
        cfg = agent.config
        self.assertEqual(cfg.agent_id, "react")
        self.assertIn("general_chat", cfg.capabilities)
        self.assertGreater(cfg.max_concurrent, 0)

    def test_validate_input_rejects_empty(self) -> None:
        from core.agents.react_agent import ReactAgent
        agent = ReactAgent()
        ok, err = agent.validate_input({"message": "   "})
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_validate_input_rejects_too_long(self) -> None:
        from core.agents.react_agent import ReactAgent
        agent = ReactAgent()
        ok, err = agent.validate_input({"message": "x" * 8001})
        self.assertFalse(ok)
        self.assertIn("8000", err or "")

    def test_validate_input_accepts_normal(self) -> None:
        from core.agents.react_agent import ReactAgent
        agent = ReactAgent()
        ok, err = agent.validate_input({"message": "你好"})
        self.assertTrue(ok)
        self.assertIsNone(err)


# ── 测试：build_react_graph 编译与最小执行 ──────────────────────────
class TestReactGraphBuild(unittest.TestCase):
    def test_compile_with_no_tools(self) -> None:
        from core.agents.react_agent import build_react_graph
        # 假 LLM：不带 tools 也能编译
        fake_llm = MagicMock()
        g = build_react_graph(fake_llm, tool_map={})
        self.assertIsNotNone(g)

    def test_compile_with_mock_tool(self) -> None:
        from core.agents.react_agent import build_react_graph
        from langchain_core.tools import tool

        @tool
        def echo(text: str) -> str:
            """回显输入。"""
            return text

        g = build_react_graph(MagicMock(), tool_map={"echo": echo})
        self.assertIsNotNone(g)


# ── 测试：SessionService 默认标题 & 锁定逻辑 ────────────────────────
class TestSessionTitleLogic(unittest.TestCase):
    def setUp(self) -> None:
        # 临时 DB
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self.tmp.close()
        # 重置 Database 单例状态，使新路径生效
        from api.v1.services.database import Database
        Database._initialized = False
        Database._db_path = None
        Database._instance = None

    def tearDown(self) -> None:
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass
        # 重置单例，避免污染后续测试
        from api.v1.services.database import Database
        Database._initialized = False
        Database._db_path = None
        Database._instance = None

    def _service(self):
        from api.v1.services.session_service import SessionService
        from api.v1.services.database import Database

        return SessionService(db=Database(db_path=self.tmp.name))

    def test_default_title_format(self) -> None:
        from api.v1.services.session_service import _default_title, _is_default_title
        title = _default_title()
        self.assertTrue(title.startswith("新会话 "))
        # 形如 "新会话 2026-06-09 14:30"
        suffix = title[len("新会话 "):]
        self.assertRegex(suffix, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertTrue(_is_default_title(title))
        self.assertTrue(_is_default_title(None))
        self.assertTrue(_is_default_title(""))
        self.assertFalse(_is_default_title("我的会话"))
        self.assertFalse(_is_default_title("审查报告"))

    def test_create_session_uses_default_title(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1")
        self.assertTrue(sess["session_title"].startswith("新会话 "))
        meta = sess.get("metadata") or {}
        self.assertNotEqual(meta.get("title_locked"), True)

    def test_create_session_with_explicit_title_locks(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1", session_title="我的项目")
        self.assertEqual(sess["session_title"], "我的项目")
        meta = sess.get("metadata") or {}
        # 显式传非默认标题 → 自动锁定
        self.assertEqual(meta.get("title_locked"), True)

    def test_update_session_title_locks(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1")
        sid = sess["session_id"]
        # 此时 title 仍是默认，update 不应锁定
        updated = svc.update_session(session_id=sid, session_title="新名字")
        meta = updated.get("metadata") or {}
        # 标题已不再是默认 → 锁定
        self.assertEqual(meta.get("title_locked"), True)
        self.assertEqual(updated["session_title"], "新名字")

    def test_update_session_merges_metadata(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1", metadata={"k1": "v1"})
        sid = sess["session_id"]
        updated = svc.update_session(
            session_id=sid, metadata={"k2": "v2"}
        )
        meta = updated.get("metadata") or {}
        self.assertEqual(meta.get("k1"), "v1")  # 旧值保留
        self.assertEqual(meta.get("k2"), "v2")  # 新值合并

    def test_summarize_skips_when_locked(self) -> None:
        svc = self._service()
        sess = svc.create_session(
            user_id="u1", session_title="显式标题", metadata={"title_locked": True}
        )
        # 由于 metadata 已有 title_locked=True（被 create_session 合并时也保留了）
        # 显式标题是用户传的非默认标题，所以一定锁定
        sid = sess["session_id"]
        new_title = svc.summarize_and_update_title(
            session_id=sid, user_text="hi", assistant_text="hello"
        )
        self.assertIsNone(new_title)

    def test_summarize_skips_when_title_not_default(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1", session_title="已自定义")
        sid = sess["session_id"]
        new_title = svc.summarize_and_update_title(
            session_id=sid, user_text="hi", assistant_text="hello"
        )
        self.assertIsNone(new_title)

    def test_summarize_skips_unknown_session(self) -> None:
        svc = self._service()
        new_title = svc.summarize_and_update_title(
            session_id="nonexistent", user_text="x", assistant_text="y"
        )
        self.assertIsNone(new_title)

    def test_summarize_writes_when_default_and_unlocked(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1")
        sid = sess["session_id"]
        # 模拟 LLM 调用
        fake_response = MagicMock()
        fake_response.content = "一个简洁的测试标题"
        with patch(
            "llm_model.reasoning_model.minimax.MinimaxReasoningModelProvider"
        ) as fake_provider_cls:
            fake_provider = fake_provider_cls.return_value
            fake_provider.get_model.return_value.invoke.return_value = fake_response
            new_title = svc.summarize_and_update_title(
                session_id=sid, user_text="请帮我", assistant_text="好的"
            )
        self.assertEqual(new_title, "一个简洁的测试标题")
        # 写回后应标记已摘要
        sess2 = svc.get_session(sid)
        meta = sess2.get("metadata") or {}
        self.assertEqual(meta.get("title_summarized"), True)
        # 已被自动改 → 默认判定为不再是默认，但 title_locked 仍为 False（因为是自动）
        self.assertNotEqual(sess2.get("session_title"), "")

    def test_summarize_second_call_is_idempotent(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1")
        sid = sess["session_id"]
        fake_response = MagicMock()
        fake_response.content = "第二次摘要"
        with patch(
            "llm_model.reasoning_model.minimax.MinimaxReasoningModelProvider"
        ) as fake_provider_cls:
            fake_provider = fake_provider_cls.return_value
            fake_provider.get_model.return_value.invoke.return_value = fake_response
            t1 = svc.summarize_and_update_title(
                session_id=sid, user_text="a", assistant_text="b"
            )
            t2 = svc.summarize_and_update_title(
                session_id=sid, user_text="c", assistant_text="d"
            )
        # 第一次应成功；第二次因标题不再是默认而跳过
        self.assertEqual(t1, "第二次摘要")
        self.assertIsNone(t2)

    def test_summarize_truncates_long_title(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1")
        sid = sess["session_id"]
        fake_response = MagicMock()
        fake_response.content = "x" * 200
        with patch(
            "llm_model.reasoning_model.minimax.MinimaxReasoningModelProvider"
        ) as fake_provider_cls:
            fake_provider = fake_provider_cls.return_value
            fake_provider.get_model.return_value.invoke.return_value = fake_response
            t = svc.summarize_and_update_title(
                session_id=sid, user_text="a", assistant_text="b"
            )
        self.assertEqual(t, "x" * 30)

    def test_summarize_handles_empty_response(self) -> None:
        svc = self._service()
        sess = svc.create_session(user_id="u1")
        sid = sess["session_id"]
        fake_response = MagicMock()
        fake_response.content = "   "
        with patch(
            "llm_model.reasoning_model.minimax.MinimaxReasoningModelProvider"
        ) as fake_provider_cls:
            fake_provider = fake_provider_cls.return_value
            fake_provider.get_model.return_value.invoke.return_value = fake_response
            t = svc.summarize_and_update_title(
                session_id=sid, user_text="a", assistant_text="b"
            )
        self.assertIsNone(t)


# ── 测试：register_react_agent 不抛异常 ─────────────────────────────
class TestReactAgentRegistration(unittest.TestCase):
    def test_register_into_registry(self) -> None:
        from core.agents.react_agent import register_react_agent
        from core.registry.agent_registry import AgentRegistry

        registry = AgentRegistry()
        register_react_agent(registry)
        agent = registry.get("react")
        self.assertIsNotNone(agent)
        self.assertEqual(agent.config.agent_id, "react")
        # 设计审查 agent 不会被本测试影响（无依赖）
        self.assertGreaterEqual(registry.agent_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
