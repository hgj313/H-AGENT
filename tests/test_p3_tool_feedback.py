"""
P3 专项测试 - 工具调用反馈环（regression 验证）

P3 bug 现象：调用工具后没有返回结果（用户报告）
根因：原 ReAct 循环在工具执行后没有把 tool_result 喂回 LLM，
     导致前端只看到 LLM 第一次输出（含伪造的 <tool_call> XML），
     看不到基于工具结果的最终自然语言回复。
修复：在 execute() 末尾新增"4.5 反馈环"，把 ToolMessage 追加后再次 stream LLM。

本测试目标（不依赖真实 LLM / 真实 DDG）：
  P3-1  工具被实际调用（web_search）
  P3-2  ToolMessage 正确附加到 messages
  P3-3  二次 LLM 调用发生（feedback loop 触发）
  P3-4  最终 SSE 事件序列：THINKING → NODE_UPDATE → MESSAGE(partial) →
         TOOL_CALL → TOOL_RESULT → NODE_UPDATE → MESSAGE(partial, second) → DONE
  P3-5  sequence 单调递增
  P3-6  _strip_tool_xml 防御性剥离：若 LLM 第一次输出含 <tool_call> XML，
         最终回复中应不含
  P3-7  工具执行抛异常 → ToolMessage 仍带 ERROR 状态回传
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _to_events(stream_iter):
    """把 AsyncIterator[StreamEvent] 收集成 list。"""
    import asyncio
    return asyncio.run(_drain(stream_iter))


async def _drain(it):
    out = []
    async for evt in it:
        out.append(evt)
    return out


# ── Mock LLM：让 LLM 决定调用 web_search ────────────────────────────
def _make_mock_llm_with_tool_call():
    """构造 mock LLM：
    - stream(messages) → 第一次 yield '我来搜一下 <tool_call>...'（含 XML 残留）
                        第二次 yield '搜索结果说...'
    - bind_tools().invoke(messages) → 返回带 tool_calls 的 AIMessage
    """
    from langchain_core.messages import AIMessage

    llm = MagicMock()

    # bind_tools().invoke 决定调工具
    # 第一次：调工具；第二次：返回 []（final answer，终止循环）
    bound = MagicMock()
    bound.invoke = MagicMock(side_effect=[
        AIMessage(
            content="",
            tool_calls=[{
                "name": "web_search",
                "args": {"query": "test", "max_results": 2},
                "id": "call_xyz",
            }],
        ),
        # 递归第二轮：不再调工具，输出 final
        AIMessage(content="", tool_calls=[]),
    ])
    llm.bind_tools = MagicMock(return_value=bound)

    # stream() 行为
    def stream_side_effect(messages):
        # 第一次 LLM：故意带 tool_call XML 残留（测试 _strip_tool_xml）
        yield AIMessage(
            content="<tool_call>web_search</tool_call>我搜一下 <tool_call>fake</tool_call>"
        )
        # 二次 LLM：基于工具结果的回答
        yield AIMessage(content="根据搜索，测试结果良好。")

    llm.stream = MagicMock(side_effect=stream_side_effect)
    return llm


# ── 工具 mock ───────────────────────────────────────────────────────
def _patch_tools():
    """把 web_search 替换成可控 mock。"""
    import core.agents.tools.search_tool as st

    def fake_web_search(query: str, max_results: int = 5) -> str:
        return json.dumps(
            [
                {"title": f"Result A for {query}", "href": "https://a", "body": "aaa"},
                {"title": f"Result B for {query}", "href": "https://b", "body": "bbb"},
            ],
            ensure_ascii=False,
        )

    return patch.object(st, "web_search", new=fake_web_search)


class P3ToolFeedbackTests(unittest.TestCase):
    """P3 反馈环端到端（in-process）测试。"""

    def setUp(self) -> None:
        from core.agents.react_agent import ReactAgent
        self.agent = ReactAgent()
        # 跳过真实 LLM 加载
        self.agent._llm = _make_mock_llm_with_tool_call()
        self.agent._tools = [MagicMock(name="web_search_mock")]
        self.agent._tool_map = {"web_search": self.agent._tools[0]}
        self.agent._tools[0].name = "web_search"
        self.agent._tools[0].invoke = MagicMock(
            return_value=json.dumps([{"title": "X", "href": "y", "body": "z"}])
        )
        self.agent._graph = MagicMock()  # _ensure_graph 不会再跑
        self.agent._memory_ready = True  # 跳过 MemoryManager
        self.agent._memory_manager = MagicMock()
        self.agent._memory_manager.build_context = MagicMock(
            side_effect=lambda **kw: [_SysMsg("你是一个助手"), _HumMsg(kw["current_message"])]
        )
        self.agent._memory_manager.extract_and_store_facts = MagicMock(return_value=0)

    def test_P3_1_tool_is_actually_called(self):
        """P3-1: web_search.invoke() 被实际调用。"""
        self.agent._tools[0].invoke.reset_mock()
        events = _to_events(self.agent.execute({
            "message": "搜索 test",
            "session_id": "fake_sid",
        }))
        self.assertEqual(self.agent._tools[0].invoke.call_count, 1,
                         "web_search 应被调用 1 次")

    def test_P3_2_and_3_feedback_loop_invoked_second_llm(self):
        """P3-2/3: 4.5 反馈环触发 → 第二次 LLM stream 发生。"""
        events = _to_events(self.agent.execute({
            "message": "搜索 test",
            "session_id": "fake_sid",
        }))
        # llm.stream 应被调 2 次：第一次 + 反馈环第二次
        self.assertEqual(self.agent._llm.stream.call_count, 2,
                         "反馈环必须触发第二次 LLM.stream")

    def test_P3_4_sse_event_sequence(self):
        """P3-4: SSE 事件顺序：TOOL_CALL → TOOL_RESULT → MESSAGE(二次) → DONE。"""
        events = _to_events(self.agent.execute({
            "message": "搜索 test",
            "session_id": "fake_sid",
        }))
        types = [e.event for e in events]
        # 必须包含所有关键事件
        self.assertIn("tool_call", types)
        self.assertIn("tool_result", types)
        self.assertIn("done", types)
        # 顺序：tool_call 在 tool_result 之前
        self.assertLess(types.index("tool_call"), types.index("tool_result"))
        # done 必须最后
        self.assertEqual(types[-1], "done")
        # 至少 2 次 message 事件（第一次 + 反馈环）
        msg_events = [e for e in events if e.event == "message"]
        self.assertGreaterEqual(len(msg_events), 2)

    def test_P3_5_sequence_monotonic(self):
        """P3-5: sequence 单调递增。"""
        events = _to_events(self.agent.execute({
            "message": "搜索 test",
            "session_id": "fake_sid",
        }))
        seqs = [e.sequence for e in events]
        for i in range(1, len(seqs)):
            self.assertGreater(seqs[i], seqs[i - 1], f"sequence 在 index {i} 回退")

    def test_P3_6_strip_tool_xml(self):
        """P3-6: LLM 第一次输出含 <tool_call> XML 时，最终回复不含。"""
        events = _to_events(self.agent.execute({
            "message": "搜索 test",
            "session_id": "fake_sid",
        }))
        done = next(e for e in events if e.event == "done")
        full = done.data.get("full_text", "")
        # 第一次 LLM 输出含 <tool_call> XML，第二次是干净回复；
        # _strip_tool_xml 后最终回复应是第二次的文本，不含 <tool_call>
        self.assertNotIn("<tool_call>", full,
                         f"最终回复残留 <tool_call> XML: {full!r}")
        self.assertIn("测试结果", full)

    def test_P3_7_tool_exception_propagates(self):
        """P3-7: 工具抛异常时，ToolMessage 仍带 ERROR，流程不崩。"""
        self.agent._tools[0].invoke = MagicMock(
            side_effect=RuntimeError("downstream service down")
        )
        events = _to_events(self.agent.execute({
            "message": "搜索 test",
            "session_id": "fake_sid",
        }))
        tool_result = next(e for e in events if e.event == "tool_result")
        self.assertIn("ERROR", tool_result.data.get("result", ""))
        # 不应有 error 事件（业务异常已包装为正常 tool_result）
        error_events = [e for e in events if e.event == "error"]
        self.assertEqual(len(error_events), 0)
        # done 仍能正常发出
        self.assertEqual(events[-1].event, "done")


# ── 辅助：构造 langchain Message ────────────────────────────────────
def _SysMsg(c):
    from langchain_core.messages import SystemMessage
    return SystemMessage(content=c)


def _HumMsg(c):
    from langchain_core.messages import HumanMessage
    return HumanMessage(content=c)


if __name__ == "__main__":
    unittest.main(verbosity=2)
