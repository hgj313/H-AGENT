"""
Executor - 任务执行器

接收 Planner 决策并执行：
- {"type":"react", "goal":...} → 单步 ReAct（直接交给 agent 主流程）
- {"type":"plan", "steps":[...]} → 拆步，每步跑一次 ReAct，汇总

执行器不直接调 LLM，而是把每一步包装成 input_data 后回调 agent 自身，
保持单一职责与可测性。
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable

from core.agents.base import StreamEvent
from api.v1.schemas.chat import StreamEventType

logger = logging.getLogger(__name__)


class Executor:
    """任务执行器。"""

    def __init__(
        self,
        react_runner: Callable[[dict[str, Any]], AsyncIterator[StreamEvent]],
    ) -> None:
        # react_runner: 接收 input_data，返回 StreamEvent 异步迭代器
        self._react_runner = react_runner

    async def run(
        self,
        plan: dict[str, Any],
        base_input: dict[str, Any],
        stream_seq_fn: Callable[[], int],
    ) -> AsyncIterator[StreamEvent]:
        """根据 plan 执行并产出事件流。"""
        ptype = plan.get("type", "react")
        if ptype == "react":
            # 单步：直接透传
            async for evt in self._react_runner(base_input):
                yield evt
            return

        if ptype == "plan":
            steps = plan.get("steps") or []
            if not steps:
                # 防御：空 steps 退化为 react
                async for evt in self._react_runner(base_input):
                    yield evt
                return

            task_id = f"plan-{uuid.uuid4().hex[:8]}"
            start_ts = time.perf_counter()
            aggregated_text = ""
            tool_calls_seen: list[dict[str, Any]] = []

            yield StreamEvent(
                event=StreamEventType.THINKING.value,
                data={"stage": "planning", "steps": steps, "agent_id": "react"},
                sequence=stream_seq_fn(),
                timestamp=_now_iso(),
                agent_id="react",
            )

            for idx, step in enumerate(steps, start=1):
                step_input = dict(base_input)
                step_input["message"] = step
                step_input["metadata"] = {
                    **base_input.get("metadata", {}),
                    "plan_step": idx,
                    "plan_total": len(steps),
                }
                yield StreamEvent(
                    event=StreamEventType.NODE_UPDATE.value,
                    data={
                        "node": f"plan_step_{idx}",
                        "status": "running",
                        "message": f"执行步骤 {idx}/{len(steps)}: {step}",
                        "agent_id": "react",
                    },
                    sequence=stream_seq_fn(),
                    timestamp=_now_iso(),
                    agent_id="react",
                )
                step_text = ""
                async for evt in self._react_runner(step_input):
                    # 收集文本用于最终汇总
                    if evt.event == StreamEventType.MESSAGE.value:
                        content = (evt.data or {}).get("content", "")
                        if isinstance(content, str):
                            step_text += content
                    elif evt.event == StreamEventType.TOOL_CALL.value:
                        tool_calls_seen.append(evt.data or {})
                    yield evt
                aggregated_text += f"\n\n[步骤 {idx}] {step}\n{step_text}".strip() + "\n"

            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            yield StreamEvent(
                event=StreamEventType.DONE.value,
                data={
                    "task_id": task_id,
                    "session_id": base_input.get("session_id") or None,
                    "duration_ms": duration_ms,
                    "tool_calls": tool_calls_seen,
                    "full_text": aggregated_text.strip(),
                    "plan_completed": True,
                },
                sequence=stream_seq_fn(),
                timestamp=_now_iso(),
                agent_id="react",
            )
            return

        # 未知类型：退化为 react
        async for evt in self._react_runner(base_input):
            yield evt


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat()
