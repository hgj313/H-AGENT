"""
P5 专项测试 - 递归 tool 链（最大深度可配置）

需求（用户决策）：
  - max_iterations 默认 5（生产级安全网）
  - 每轮重新决策：tool_calls 决定是否再调
  - 每轮标注 turn=N（前端可显示进度）

覆盖：
  P5-1  1 轮 tool 链：1 LLM → 1 tool → 1 LLM(final) → done
  P5-2  3 轮 tool 链：每轮都再调工具，直到第 3 轮才出 final
  P5-3  max_iterations 强制收尾：LLM 持续要调工具，到达上限强制 done
  P5-4  turn 字段在所有相关事件中正确递增（node_update / tool_call /
        tool_result / message.partial / done）
  P5-5  done 事件含 turn / max_iterations / max_iterations_reached 字段
  P5-6  无 tool_calls 时 turn=0，不进入循环
  P5-7  工具异常仍能完成本轮（不破坏循环）
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _to_events(stream_iter):
    return asyncio.run(_drain(stream_iter))


async def _drain(it):
    out = []
    async for evt in it:
        out.append(evt)
    return out


# ── Mock LLM 工厂 ─────────────────────────────────────────────
def _make_mock_llm(*, rounds: list[list[dict[str, Any]]] | int, final_text: str = "完成"):
    """构造 mock LLM，rounds 控制每轮 invoke() 返回的 tool_calls。

    rounds 用法：
      - int N：LLM 前 N 次 invoke 都返回 [{name: web_search, ...}]，
                第 N+1 次返回 []  →  共执行 N 轮
      - list[List[TC]]：精确控制每轮 invoke 返回的 tool_calls 列表
                       最后一个 [] 表示 final
    """
    from langchain_core.messages import AIMessage

    if isinstance(rounds, int):
        rounds_list = [
            [{"name": "web_search", "args": {"query": "x"}, "id": f"c{i}"}]
            for i in range(rounds)
        ] + [[]]  # 最后一轮：final，无 tool_calls
    else:
        rounds_list = list(rounds) + [[]]
        if rounds_list[-1]:
            rounds_list.append([])

    llm = MagicMock()
    bound = MagicMock()

    decisions: list[AIMessage] = []
    for i, tcs in enumerate(rounds_list):
        decisions.append(AIMessage(content="", tool_calls=tcs))
    bound.invoke = MagicMock(side_effect=decisions)
    llm.bind_tools = MagicMock(return_value=bound)

    # stream()：每次 yield final_text 的内容
    def stream_side_effect(messages):
        yield AIMessage(content=final_text)
    llm.stream = MagicMock(side_effect=stream_side_effect)
    return llm


class P5RecursiveToolChainTests(unittest.TestCase):
    def _build_agent(self, llm, max_iter: int = 5):
        from core.agents.react_agent import ReactAgent
        agent = ReactAgent()
        agent._llm = llm
        agent._tools = [MagicMock(name="web_search_mock")]
        agent._tool_map = {"web_search": agent._tools[0]}
        agent._tools[0].name = "web_search"
        agent._tools[0].invoke = MagicMock(
            return_value=json.dumps({"hits": 3, "sample": ["A", "B", "C"]})
        )
        agent._graph = MagicMock()
        agent._memory_ready = True
        agent._memory_manager = MagicMock()
        agent._memory_manager.build_context = MagicMock(
            side_effect=lambda **kw: [
                _SysMsg("你是一个助手"),
                _HumMsg(kw["current_message"]),
            ]
        )
        agent._memory_manager.extract_and_store_facts = MagicMock(return_value=0)
        agent._max_iterations = max_iter
        return agent

    # ── P5-1 ────────────────────────────────────────────────
    def test_P5_1_single_turn(self):
        llm = _make_mock_llm(rounds=1, final_text="搜索完成")
        agent = self._build_agent(llm)
        events = _to_events(agent.execute({"message": "搜 test", "session_id": "s1"}))
        tool_calls = [e for e in events if e.event == "tool_call"]
        self.assertEqual(len(tool_calls), 1)
        # 第一轮 turn=1
        self.assertEqual(tool_calls[0].data.get("turn"), 1)
        # done 含 turn=1
        done = next(e for e in events if e.event == "done")
        self.assertEqual(done.data.get("turn"), 1)
        self.assertFalse(done.data.get("max_iterations_reached"))
        # llm.invoke 调用 2 次（决策 + 1 轮后续决策） = N+1（N=1）
        self.assertEqual(agent._llm.bind_tools().invoke.call_count, 2)

    # ── P5-2 ────────────────────────────────────────────────
    def test_P5_2_three_turns(self):
        llm = _make_mock_llm(rounds=3, final_text="三轮搜索完成")
        agent = self._build_agent(llm)
        events = _to_events(agent.execute({"message": "深度搜", "session_id": "s1"}))
        tool_calls = [e for e in events if e.event == "tool_call"]
        self.assertEqual(len(tool_calls), 3)
        # 各轮 turn
        turns = [tc.data.get("turn") for tc in tool_calls]
        self.assertEqual(turns, [1, 2, 3])
        # done 含 turn=3
        done = next(e for e in events if e.event == "done")
        self.assertEqual(done.data.get("turn"), 3)
        # 工具 invoke 调 3 次
        self.assertEqual(agent._tools[0].invoke.call_count, 3)

    # ── P5-3 ────────────────────────────────────────────────
    def test_P5_3_max_iterations_force_stop(self):
        # LLM 一直要调工具（10 轮），但 max_iter=3 → 应强制 3 轮后退出
        llm = _make_mock_llm(rounds=10, final_text="部分结果")
        agent = self._build_agent(llm, max_iter=3)
        events = _to_events(agent.execute({"message": "无限搜", "session_id": "s1"}))
        tool_calls = [e for e in events if e.event == "tool_call"]
        # 只应执行 3 轮（虽然决策列表里 10 轮都要调）
        self.assertEqual(len(tool_calls), 3)
        # done 应标记 max_iterations_reached=True
        done = next(e for e in events if e.event == "done")
        self.assertTrue(done.data.get("max_iterations_reached"))
        self.assertEqual(done.data.get("turn"), 3)
        self.assertEqual(done.data.get("max_iterations"), 3)
        # 应有 warning node_update
        warns = [
            e for e in events
            if e.event == "node_update"
            and (e.data or {}).get("status") == "warning"
        ]
        self.assertEqual(len(warns), 1)
        self.assertIn("最大递归深度", warns[0].data.get("message", ""))

    # ── P5-4 ────────────────────────────────────────────────
    def test_P5_4_turn_field_consistent(self):
        llm = _make_mock_llm(rounds=2, final_text="ok")
        agent = self._build_agent(llm)
        events = _to_events(agent.execute({"message": "q", "session_id": "s1"}))
        # 找到每个 turn 范围
        node_updates = [e for e in events if e.event == "node_update"]
        # turn 1 + turn 1 节点更新（执行 + 重决策），turn 2 同理
        turn_2_nodes = [
            n for n in node_updates if (n.data or {}).get("turn") == 2
        ]
        # turn=2 节点至少 1 个（执行）
        self.assertGreaterEqual(len(turn_2_nodes), 1)
        # tool_call turn=2
        tc2 = [e for e in events if e.event == "tool_call" and e.data.get("turn") == 2]
        self.assertEqual(len(tc2), 1)
        # tool_result turn=2
        tr2 = [e for e in events if e.event == "tool_result" and e.data.get("turn") == 2]
        self.assertEqual(len(tr2), 1)
        # message partial 含 turn=1 / turn=2
        msgs_1 = [e for e in events if e.event == "message" and e.data.get("turn") == 1]
        msgs_2 = [e for e in events if e.event == "message" and e.data.get("turn") == 2]
        self.assertGreater(len(msgs_1), 0)
        self.assertGreater(len(msgs_2), 0)

    # ── P5-5 ────────────────────────────────────────────────
    def test_P5_5_done_event_includes_iter_meta(self):
        llm = _make_mock_llm(rounds=1, final_text="final")
        agent = self._build_agent(llm, max_iter=5)
        events = _to_events(agent.execute({"message": "q", "session_id": "s1"}))
        done = next(e for e in events if e.event == "done")
        self.assertIn("turn", done.data)
        self.assertIn("max_iterations", done.data)
        self.assertIn("max_iterations_reached", done.data)
        self.assertEqual(done.data["max_iterations"], 5)
        self.assertEqual(done.data["turn"], 1)
        self.assertFalse(done.data["max_iterations_reached"])

    # ── P5-6 ────────────────────────────────────────────────
    def test_P5_6_no_tool_calls(self):
        # LLM 第一次决策就返回 []（不调工具）
        llm = _make_mock_llm(rounds=0, final_text="直接回答")
        agent = self._build_agent(llm)
        events = _to_events(agent.execute({"message": "q", "session_id": "s1"}))
        tool_calls = [e for e in events if e.event == "tool_call"]
        self.assertEqual(len(tool_calls), 0)
        # turn=0
        done = next(e for e in events if e.event == "done")
        self.assertEqual(done.data.get("turn"), 0)

    # ── P5-7 ────────────────────────────────────────────────
    def test_P5_7_tool_exception_does_not_break_loop(self):
        from langchain_core.messages import AIMessage
        llm = MagicMock()
        bound = MagicMock()
        # 第一轮：调工具（异常）；第二轮：final
        bound.invoke = MagicMock(side_effect=[
            AIMessage(content="", tool_calls=[
                {"name": "web_search", "args": {"query": "x"}, "id": "c1"}
            ]),
            AIMessage(content="", tool_calls=[]),
        ])
        llm.bind_tools = MagicMock(return_value=bound)
        llm.stream = MagicMock(side_effect=lambda msgs: iter([AIMessage(content="recovered")]))
        agent = self._build_agent(llm)
        agent._tools[0].invoke = MagicMock(side_effect=RuntimeError("downstream"))

        events = _to_events(agent.execute({"message": "q", "session_id": "s1"}))
        # 工具异常但流程不崩
        tool_result = next(e for e in events if e.event == "tool_result")
        self.assertIn("ERROR", tool_result.data.get("result", ""))
        # 仍有 done
        self.assertEqual(events[-1].event, "done")
        # turn=1（虽然工具异常，仍只跑了 1 轮，第二次决策时 tool_calls=[] → 退出）
        done = next(e for e in events if e.event == "done")
        self.assertEqual(done.data.get("turn"), 1)


def _SysMsg(c):
    from langchain_core.messages import SystemMessage
    return SystemMessage(content=c)


def _HumMsg(c):
    from langchain_core.messages import HumanMessage
    return HumanMessage(content=c)


if __name__ == "__main__":
    unittest.main(verbosity=2)
