"""
会话服务模块。

提供会话的CRUD操作，包括：
- 新建会话（默认标题自动生成）
- 查询会话列表
- 更新会话信息（手动改标题时自动锁定，避免被摘要覆写）
- 删除会话（软删除）
- 首轮对话完成后异步生成摘要标题

设计要点：
- 默认标题格式：``新会话 YYYY-MM-DD HH:MM``
- 摘要生成幂等：若 ``metadata.title_locked`` 为 True 则跳过
- 摘要生成失败不影响主流程，仅记日志
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from .database import Database, get_database

logger = logging.getLogger(__name__)

# 默认标题前缀（用于判定"是否还是默认名"，避免覆写用户已改的标题）
DEFAULT_TITLE_PREFIX = "新会话"

# 摘要 LLM 提示词
_SUMMARY_SYSTEM_PROMPT = (
    "你是一名会话标题生成助手。\n"
    "根据用户与助手的第一轮对话，生成一个不超过 20 个字符的简洁中文标题。\n"
    "要求：\n"
    "1. 直接输出标题文字，不要加引号、序号、解释\n"
    "2. 使用与对话相同的语言\n"
    "3. 抓取核心主题/意图，去掉寒暄与客套\n"
)


def _default_title() -> str:
    """生成默认会话标题：``新会话 YYYY-MM-DD HH:MM``。"""
    return f"{DEFAULT_TITLE_PREFIX} {datetime.now().strftime('%Y-%m-%d %H:%M')}"


def _is_default_title(title: Optional[str]) -> bool:
    """判断当前标题是否仍是默认标题（可被摘要覆写）。"""
    if not title:
        return True
    return title.startswith(DEFAULT_TITLE_PREFIX)


def _extract_text(message: Any) -> str:
    """从 LangChain AIMessage 抽取纯文本，兼容 OpenAI(str) 与 Anthropic(list) 两种 content 格式。"""
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Anthropic 风格：{type: "text", text: "..."}
                if block.get("type") in (None, "text") and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                # 兼容 reasoning / 其他带 text 字段的块
                elif isinstance(block.get("text"), str):
                    parts.append(block["text"])
            else:
                # LangChain ContentBlock 对象
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    # 兜底：其他类型直接 str()
    return str(content)


class SessionService:
    """会话服务，管理对话会话的生命周期。"""
    
    def __init__(self, db: Optional[Database] = None) -> None:
        """
        初始化会话服务。
        
        Args:
            db: 数据库实例，如果不提供则使用默认实例
        """
        self.db = db or get_database()
    
    def create_session(
        self,
        user_id: str,
        session_title: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        创建新会话。
        
        Args:
            user_id: 用户ID
            session_title: 会话标题（可选，默认为"新对话"）
            metadata: 扩展元数据（可选）
            
        Returns:
            新创建的会话信息
        """
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        # 若未提供标题，则使用默认标题（带时间戳）
        final_title = session_title or _default_title()

        # 用户显式指定非默认标题 → 视为"已被用户接管"，自动锁定
        final_metadata: dict[str, Any] = dict(metadata or {})
        if not _is_default_title(final_title):
            final_metadata["title_locked"] = True
            final_metadata["title_locked_at"] = now

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, user_id, session_title, create_at, update_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    final_title,
                    now,
                    now,
                    json.dumps(final_metadata, ensure_ascii=False),
                ),
            )

        logger.info(f"创建会话成功: session_id={session_id}, user_id={user_id}")

        return {
            "session_id": session_id,
            "user_id": user_id,
            "session_title": final_title,
            "create_at": now,
            "update_at": now,
            "is_active": 1,
            "metadata": final_metadata,
        }
    
    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """
        获取会话详情。
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话信息，如果不存在返回None
        """
        row = self.db.fetch_one(
            """
            SELECT session_id, user_id, session_title, create_at, update_at, 
                   is_active, last_checkpoint_id, metadata
            FROM sessions 
            WHERE session_id = ?
            """,
            (session_id,),
        )
        
        if row and row.get("metadata"):
            try:
                row["metadata"] = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                row["metadata"] = {}
        
        return row
    
    def list_sessions(
        self,
        user_id: str,
        is_active: int = 1,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        获取用户会话列表。
        
        Args:
            user_id: 用户ID
            is_active: 会话状态过滤（1=活跃，0=归档）
            limit: 返回数量限制
            offset: 分页偏移量
            
        Returns:
            会话列表，按更新时间倒序排列
        """
        rows = self.db.fetch_all(
            """
            SELECT session_id, user_id, session_title, create_at, update_at, 
                   is_active, last_checkpoint_id, metadata
            FROM sessions 
            WHERE user_id = ? AND is_active = ?
            ORDER BY update_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, is_active, limit, offset),
        )
        
        for row in rows:
            if row.get("metadata"):
                try:
                    row["metadata"] = json.loads(row["metadata"])
                except (json.JSONDecodeError, TypeError):
                    row["metadata"] = {}

        return rows

    # ── 首轮摘要（D1 决策：后端异步触发） ────────────────────────────
    def summarize_and_update_title(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> Optional[str]:
        """根据首轮对话生成会话标题并写回。

        幂等性：
            - 会话不存在 → 返回 None
            - ``metadata.title_locked == True`` → 跳过（用户已手动改过标题）
            - ``session_title`` 已被改成非默认标题 → 视为已锁定，跳过
            - LLM 不可用或调用失败 → 返回 None，保留默认标题，不抛异常

        Args:
            session_id: 会话ID
            user_text: 用户首条消息
            assistant_text: 助手首条回复

        Returns:
            新写入的标题字符串；若未执行写入则返回 None。
        """
        sess = self.get_session(session_id)
        if sess is None:
            logger.warning("summarize_and_update_title: 会话不存在 %s", session_id)
            return None

        # 1) 锁检查
        metadata = sess.get("metadata") or {}
        if metadata.get("title_locked") is True:
            logger.debug("会话 %s 标题已锁定，跳过摘要", session_id)
            return None

        # 2) 当前标题已不是默认 → 视为锁定
        if not _is_default_title(sess.get("session_title")):
            logger.debug("会话 %s 标题已被修改，跳过摘要", session_id)
            return None

        # 3) LLM 生成标题
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from llm_model.reasoning_model.minimax import (
                MinimaxReasoningModelProvider,
            )

            provider = MinimaxReasoningModelProvider()
            llm = provider.get_model()

            user_payload = (
                f"用户：{(user_text or '').strip()[:500]}\n"
                f"助手：{(assistant_text or '').strip()[:500]}\n"
                "请生成标题："
            )
            response = llm.invoke(
                [
                    SystemMessage(content=_SUMMARY_SYSTEM_PROMPT),
                    HumanMessage(content=user_payload),
                ]
            )
            # 兼容两种 content 形态：
            # - OpenAI 风格：response.content 是 str
            # - Anthropic 风格：response.content 是 list[ {type, text}, ... ]
            new_title = _extract_text(response).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("会话 %s 标题摘要失败: %s", session_id, exc)
            return None

        # 4) 清洗与截断
        new_title = new_title.strip().strip("\"'「」『』、。,.;；:：")
        if not new_title:
            return None
        if len(new_title) > 30:
            new_title = new_title[:30]

        # 5) 二次检查：摘要过程可能耗时，期间用户可能已改标题
        sess_again = self.get_session(session_id)
        if sess_again is None:
            return None
        meta_again = sess_again.get("metadata") or {}
        if meta_again.get("title_locked") is True:
            return None
        if not _is_default_title(sess_again.get("session_title")):
            return None

        # 6) 写回（不再触发 title_locked，因为这本身就是自动行为）
        merged = dict(meta_again)
        merged["title_summarized"] = True
        merged["title_summarized_at"] = datetime.now().isoformat()
        self.update_session(
            session_id=session_id,
            session_title=new_title,
            metadata=merged,
        )
        logger.info("会话 %s 标题已摘要为: %s", session_id, new_title)
        return new_title
    
    def update_session(
        self,
        session_id: str,
        session_title: Optional[str] = None,
        is_active: Optional[int] = None,
        last_checkpoint_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        更新会话信息。

        行为约定：
        - 当显式传入 ``session_title`` 且当前标题不是默认标题时，自动设置
          ``metadata.title_locked = True``，防止后续首轮摘要覆写用户已修改的标题。
        - 传入 ``metadata`` 时深合并而非覆盖，保留 ``title_locked`` 等已有键。

        Args:
            session_id: 会话ID
            session_title: 新标题（可选）
            is_active: 新状态（可选）
            last_checkpoint_id: 最新检查点ID（可选）
            metadata: 新元数据（可选，会与现有 metadata 浅合并）

        Returns:
            更新后的会话信息
        """
        # 先取当前会话，用于合并 metadata 与判断"是否还是默认标题"
        current = self.get_session(session_id)
        if current is None:
            return None

        # 浅合并 metadata：新值优先，但保留旧值里未提供的键
        merged_metadata: dict[str, Any] = dict(current.get("metadata") or {})
        if metadata is not None:
            for k, v in metadata.items():
                merged_metadata[k] = v

        update_fields: list[str] = []
        params: list[Any] = []

        if session_title is not None:
            update_fields.append("session_title = ?")
            params.append(session_title)
            # 新标题不是默认 → 用户主动设置/修改 → 加锁，避免后续首轮摘要覆写
            if not _is_default_title(session_title):
                merged_metadata["title_locked"] = True
                merged_metadata["title_locked_at"] = datetime.now().isoformat()

        if is_active is not None:
            update_fields.append("is_active = ?")
            params.append(is_active)

        if last_checkpoint_id is not None:
            update_fields.append("last_checkpoint_id = ?")
            params.append(last_checkpoint_id)

        # metadata 即使没显式传，只要前面因 title 变化产生了合并，也要写回
        if metadata is not None or merged_metadata != (current.get("metadata") or {}):
            update_fields.append("metadata = ?")
            params.append(json.dumps(merged_metadata, ensure_ascii=False))

        if not update_fields:
            return current

        # 更新 update_at 时间戳
        update_fields.append("update_at = ?")
        params.append(datetime.now().isoformat())
        params.append(session_id)

        with self.db.transaction() as conn:
            conn.execute(
                f"""
                UPDATE sessions
                SET {', '.join(update_fields)}
                WHERE session_id = ?
                """,
                tuple(params),
            )

        return self.get_session(session_id)
    
    def update_session_timestamp(self, session_id: str) -> None:
        """
        更新会话的最后更新时间。
        
        Args:
            session_id: 会话ID
        """
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE sessions SET update_at = ? WHERE session_id = ?",
                (datetime.now().isoformat(), session_id),
            )
    
    def delete_session(self, session_id: str, hard_delete: bool = False) -> bool:
        """
        删除会话。
        
        Args:
            session_id: 会话ID
            hard_delete: 是否硬删除（默认软删除）
            
        Returns:
            是否删除成功
        """
        if hard_delete:
            with self.db.transaction() as conn:
                # 外键约束会自动级联删除关联的messages和checkpoints
                cursor = conn.execute(
                    "DELETE FROM sessions WHERE session_id = ?",
                    (session_id,),
                )
                return cursor.rowcount > 0
        else:
            return self.update_session(session_id, is_active=0) is not None
    
    def restore_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """
        恢复已归档的会话。
        
        Args:
            session_id: 会话ID
            
        Returns:
            恢复后的会话信息
        """
        return self.update_session(session_id, is_active=1)
    
    def get_session_count(self, user_id: str, is_active: int = 1) -> int:
        """
        获取用户会话数量。
        
        Args:
            user_id: 用户ID
            is_active: 会话状态过滤
            
        Returns:
            会话数量
        """
        row = self.db.fetch_one(
            "SELECT COUNT(*) as count FROM sessions WHERE user_id = ? AND is_active = ?",
            (user_id, is_active),
        )
        return row["count"] if row else 0
    
    def search_sessions(
        self,
        user_id: str,
        keyword: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        搜索会话（按标题模糊匹配）。
        
        Args:
            user_id: 用户ID
            keyword: 搜索关键词
            limit: 返回数量限制
            
        Returns:
            匹配的会话列表
        """
        rows = self.db.fetch_all(
            """
            SELECT session_id, user_id, session_title, create_at, update_at, 
                   is_active, last_checkpoint_id, metadata
            FROM sessions 
            WHERE user_id = ? AND is_active = 1 AND session_title LIKE ?
            ORDER BY update_at DESC
            LIMIT ?
            """,
            (user_id, f"%{keyword}%", limit),
        )
        
        for row in rows:
            if row.get("metadata"):
                try:
                    row["metadata"] = json.loads(row["metadata"])
                except (json.JSONDecodeError, TypeError):
                    row["metadata"] = {}
        
        return rows
