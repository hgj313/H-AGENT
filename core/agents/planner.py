"""
Planner - 任务规划器

负责在 ReAct 循环前决定处理模式：
- {"type": "react"}：单步工具调用即可完成（默认）
- {"type": "plan", "steps": [...]}：需要多步拆解（先做 step1 拿结果再做 step2）

设计取舍：
- 同步 LLM 调用（一次 ~2-3s）
- JSON 输出 + 宽松解析（fallback 到 "react"）
- 启发式：含 "然后"/"再"/"接着"/"并且" 等连接词 → 倾向 plan
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_PLANNER_SYSTEM = (
    "你是任务规划器。分析用户请求，决定最合适的处理方式。\n"
    "返回严格 JSON（无其他文字）：\n"
    '- {"type":"react","goal":"..."}：单步可完成（默认）\n'
    '- {"type":"plan","steps":["步骤1","步骤2",...]}：多步任务需拆解\n\n'
    "判定规则：\n"
    "- 单个明确问题/请求/动作 → react\n"
    "- 含「然后/再/接着/并且/以及/并/之后/分步」等连接词 → plan\n"
    "- 含 2 个以上独立目标 → plan"
)

_PLAN_RE_HINT = re.compile(r"(然后|接着|之后|并且|以及|再|分步|最后|首先.*然后)")


class Planner:
    """任务规划器。"""

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm

    async def decide(
        self, user_message: str, context_hint: str = ""
    ) -> dict[str, Any]:
        """返回 {"type": "react" | "plan", ...}。"""
        # 启发式先快速分类
        if _PLAN_RE_HINT.search(user_message):
            heuristic = "plan"
        else:
            heuristic = "react"

        # 简单消息直接走启发式（省一次 LLM 调用）
        if len(user_message) <= 20 and heuristic == "react":
            return {"type": "react", "goal": user_message}

        # 复杂场景调 LLM 二次确认
        try:
            user_prompt = (
                f"用户消息：{user_message}\n"
                f"上下文摘要：{context_hint or '（无）'}\n\n"
                "返回 JSON："
            )
            resp = await self.llm.ainvoke(
                [
                    SystemMessage(content=_PLANNER_SYSTEM),
                    HumanMessage(content=user_prompt),
                ]
            )
            content = _extract_text(resp.content)
            data = _safe_parse_json(content)
            if data and data.get("type") in ("react", "plan"):
                if data["type"] == "plan" and not data.get("steps"):
                    return {"type": "react", "goal": user_message}
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Planner.ainvoke 失败: %s", exc)

        # Fallback
        if heuristic == "plan":
            steps = _heuristic_split(user_message)
            return {"type": "plan", "steps": steps}
        return {"type": "react", "goal": user_message}


def _heuristic_split(message: str) -> list[str]:
    """按连接词简单拆句。"""
    parts = re.split(r"(然后|接着|之后|并且|以及|再|分步|最后)", message)
    out: list[str] = []
    current = ""
    for p in parts:
        if p in ("然后", "接着", "之后", "并且", "以及", "再", "分步", "最后"):
            if current.strip():
                out.append(current.strip())
            current = ""
        else:
            current += p
    if current.strip():
        out.append(current.strip())
    if not out:
        out = [message]
    return out


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(item["text"])
                elif "text" in item and item["text"]:
                    parts.append(item["text"])
        return "".join(parts)
    if hasattr(content, "text"):
        return getattr(content, "text", "")
    return str(content or "")


def _safe_parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    # 尝试整段
    try:
        return json.loads(text.strip())
    except Exception:  # noqa: BLE001
        pass
    # 尝试抽取首段 {...}
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return None
    return None
