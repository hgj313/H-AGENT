"""
HistorySummarizer - 历史对话摘要器

把超出滑动窗口的旧消息压缩为结构化摘要，缓存到 session.metadata。
缓存键：history_summary_count（已摘要的消息数）；新消息增长才重算。

设计取舍：
- 同步执行（简单可靠，~2-5s 延迟）
- 缓存到 session metadata（避免每轮重算）
- 摘要内容控制在 ≤200 字（节省 token）
- 重要消息（工具结果/含身份关键词）不参与摘要，直接保留
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "你是对话历史压缩器。请将以下对话压缩为简洁摘要（中文，≤200 字）。\n"
    "保留：用户身份（姓名/角色）、关键决策、重要事实、用户偏好。\n"
    "忽略：寒暄、重复信息、工具调用过程。\n"
    "输出纯文本摘要，不要使用任何前缀或列表标记。"
)

_IMPORTANT_KEYWORDS = (
    "我叫", "我是", "我的名字", "我的工作", "我住在", "我喜欢", "我讨厌",
    "记住我", "记得", "记一下", "提醒我",
)


class HistorySummarizer:
    """历史摘要器。"""

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm

    def summarize(self, messages: list[dict[str, Any]]) -> str:
        """对一组消息生成摘要。"""
        if not messages:
            return ""
        text = _messages_to_text(messages)
        if not text.strip():
            return ""
        try:
            resp = self.llm.invoke(
                [SystemMessage(content=_SUMMARY_SYSTEM), HumanMessage(content=text)]
            )
            content = _extract_text(resp.content)
            return content.strip()[:1000]  # 兜底截断
        except Exception as exc:  # noqa: BLE001
            logger.warning("摘要生成失败: %s", exc)
            return ""

    @staticmethod
    def is_important(message: dict[str, Any]) -> bool:
        """判断消息是否重要（不参与摘要，需保留原始）。"""
        content = (message.get("content") or "").strip()
        if not content:
            return False
        # 工具结果/工具调用 → 保留
        if message.get("role") in ("tool",) or message.get("message_type") in (
            "tool_call", "tool_result"
        ):
            return True
        # 助手消息包含 XML 工具调用 → 重要
        if "<tool_call" in content or "<tool_call>" in content:
            return True
        # 包含身份/偏好关键词 → 保留
        for kw in _IMPORTANT_KEYWORDS:
            if kw in content:
                return True
        return False

    @staticmethod
    def partition(
        messages: list[dict[str, Any]], k: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """将消息分为 (重要且在窗口外, 普通且在窗口外)。

        规则：
        - 最近 k 条：原样保留（在窗口内）
        - 超出窗口：重要消息 → 重要组；普通消息 → 摘要组
        - k=0：所有消息视为超出窗口（用于测试全量摘要场景）
        """
        if k > 0 and len(messages) <= k:
            return [], []
        out_of_window = messages[:-k] if k > 0 else list(messages)
        important: list[dict[str, Any]] = []
        normal: list[dict[str, Any]] = []
        for m in out_of_window:
            if HistorySummarizer.is_important(m):
                important.append(m)
            else:
                normal.append(m)
        return important, normal


def _messages_to_text(messages: Iterable[dict[str, Any]]) -> str:
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"用户: {content}")
        elif role == "assistant":
            lines.append(f"助手: {content}")
        else:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _extract_text(content: Any) -> str:
    """兼容 Anthropic SDK 的 list[dict] / 字符串 / ContentBlock。"""
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
