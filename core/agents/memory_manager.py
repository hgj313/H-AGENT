"""
MemoryManager - 记忆编排器

按三层组装 LLM 上下文：
1. 长期记忆：LongTermStore.search(user_id, query, top_k=5) — 命中即注入 system
2. 短期记忆：MessageService.get_active_messages(session_id, limit=200) 取全量
   - 滑动窗口内：原生 HumanMessage/AIMessage
   - 滑动窗口外：经 HistorySummarizer 压缩（缓存到 session.metadata）
3. 重要消息（工具结果/含身份关键词）：不被摘要，强制保留

工作记忆：当前 plan 步骤状态（由 Executor 写入 metadata）
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from core.memory.long_term_store import LongTermStore
from core.memory.summarizer import HistorySummarizer

logger = logging.getLogger(__name__)

_BASE_SYSTEM = (
    "你是 H-Agent 的通用对话助手。\n"
    "行为准则：\n"
    "1. 回答需基于提供的「用户已知信息」与「历史摘要」\n"
    "2. 若用户问及历史信息而你未在上下文中看到，礼貌地指出信息不足，"
    "不要编造\n"
    "3. 回答简洁、自然，必要时使用工具\n"
    "4. 工具调用遵循 bind_tools 协议，不要伪造 <tool_call> XML"
)


class MemoryManager:
    """记忆编排器。"""

    def __init__(
        self,
        llm: BaseChatModel,
        long_term: LongTermStore,
        message_service: Any,
        session_service: Any,
        k: int = 10,
    ) -> None:
        self.llm = llm
        self.long_term = long_term
        self.message_service = message_service
        self.session_service = session_service
        self.summarizer = HistorySummarizer(llm)
        self.k = k

    # ── 上下文构建 ───────────────────────────────────────────────
    def build_context(
        self,
        session_id: str,
        user_id: str,
        current_message: str,
    ) -> list[BaseMessage]:
        """构建 LLM 上下文消息列表。"""
        # 1) 长期事实
        facts = self.long_term.search(user_id, current_message, limit=5)
        # 2) 全量历史
        all_msgs = self._load_history(session_id)
        # 3) 拆分窗口内/外
        recent = all_msgs[-self.k :] if all_msgs else []
        older = all_msgs[: -self.k] if len(all_msgs) > self.k else []
        # 4) 拆分重要/普通
        important_older, normal_older = HistorySummarizer.partition(older, self.k)
        # 5) 摘要（缓存）
        summary = self._get_or_compute_summary(
            session_id, normal_older
        )
        # 6) 组装 system
        system = self._build_system(facts, summary, len(important_older))
        # 7) 组装消息
        messages: list[BaseMessage] = [system]
        # 窗口外重要消息：以"用户:"前缀塞进 system 之后（保留原始信息）
        for m in important_older[-5:]:  # 最多 5 条
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        # 窗口内：原生
        for m in recent:
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        # 当前消息
        messages.append(HumanMessage(content=current_message))
        return messages

    # ── 长期事实抽取 ─────────────────────────────────────────────
    def extract_and_store_facts(
        self,
        session_id: str,
        user_id: str,
        user_text: str,
        assistant_text: str,
    ) -> int:
        """从本轮对话抽取事实并写入长期记忆。返回写入条数。"""
        if not user_id or not user_text:
            return 0
        prompt = (
            "分析以下对话，提取关于用户的事实。\n"
            "每行一条，格式：[类别] 事实内容\n"
            "类别：身份 / 偏好 / 背景 / 工作 / 其他\n"
            "没有事实可提取时，输出「无」。\n\n"
            f"用户：{user_text}\n"
            f"助手：{assistant_text}\n"
        )
        try:
            resp = self.llm.invoke(
                [
                    SystemMessage(
                        content="你是事实提取器。严格按要求输出。"
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            text = self.summarizer._extract_text(resp.content) if hasattr(
                self.summarizer, "_extract_text"
            ) else _extract_text(resp.content)
            text = (text or "").strip()
            if not text or text == "无":
                return 0
            facts = _parse_facts(text)
            return self.long_term.add_facts_bulk(user_id, facts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fact extraction failed: %s", exc)
            return 0

    # ── 内部：摘要缓存 ──────────────────────────────────────────
    def _get_or_compute_summary(
        self, session_id: str, normal_older: list[dict[str, Any]]
    ) -> str:
        # 先查缓存（即使 normal_older 为空，也要把已有摘要带进上下文）
        session = self.session_service.get_session(session_id)
        meta = _safe_meta(session)
        cached = meta.get("history_summary", "")
        cached_count = int(meta.get("history_summary_count", 0))
        # 若没有新内容需要摘要，直接返回缓存
        if not normal_older:
            return cached
        # 若缓存有效（消息数未变），用缓存
        if cached and cached_count == len(normal_older):
            return cached
        summary = self.summarizer.summarize(normal_older)
        # 写回
        try:
            new_meta = {**meta, "history_summary": summary, "history_summary_count": len(normal_older)}
            self.session_service.update_session(
                session_id=session_id, metadata=new_meta
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("缓存摘要写回失败: %s", exc)
        return summary

    # ── 内部：历史加载 ──────────────────────────────────────────
    def _load_history(self, session_id: str) -> list[dict[str, Any]]:
        if not session_id:
            return []
        try:
            return self.message_service.get_active_messages(
                session_id=session_id, limit=200
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载历史失败: %s", exc)
            return []

    # ── 内部：system 拼装 ───────────────────────────────────────
    def _build_system(
        self,
        facts: list[dict[str, str]],
        summary: str,
        important_count: int,
    ) -> SystemMessage:
        parts: list[str] = [_BASE_SYSTEM]
        if facts:
            parts.append("\n## 你了解用户的以下信息")
            for f in facts:
                parts.append(f"- {f.get('text','')}")
        if summary:
            parts.append(f"\n## 对话历史摘要\n{summary}")
        if important_count:
            parts.append(
                f"\n## 重要历史消息（{important_count} 条已保留原始内容在上下文中）"
            )
        return SystemMessage(content="\n".join(parts))


# ── 工具函数 ──────────────────────────────────────────────────────
def session(_id: str) -> str:
    return _id


def _safe_meta(session: Any) -> dict[str, Any]:
    if not session:
        return {}
    meta = session.get("metadata") if isinstance(session, dict) else None
    if not meta:
        return {}
    if isinstance(meta, str):
        try:
            return json.loads(meta) or {}
        except Exception:  # noqa: BLE001
            return {}
    return dict(meta)


def _parse_facts(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip().lstrip("-•*").strip()
        if not line or line == "无":
            continue
        category = "other"
        content = line
        if line.startswith("[") and "]" in line:
            end = line.find("]")
            cat = line[1:end].strip()
            content = line[end + 1 :].strip()
            # 规范化类别
            mapping = {
                "身份": "identity",
                "偏好": "preference",
                "背景": "context",
                "工作": "work",
                "其他": "other",
            }
            category = mapping.get(cat, cat.lower() or "other")
        if content:
            out.append({"text": content, "category": category})
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
