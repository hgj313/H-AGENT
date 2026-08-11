"""
消息服务模块。

提供消息的CRUD操作，包括：
- 创建消息
- 查询消息列表
- 更新消息状态
- 撤销消息（软删除）
- 对话树遍历
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from .database import Database, get_database

logger = logging.getLogger(__name__)


class MessageService:
    """消息服务，管理对话消息的生命周期。"""
    
    def __init__(self, db: Optional[Database] = None) -> None:
        """
        初始化消息服务。
        
        Args:
            db: 数据库实例，如果不提供则使用默认实例
        """
        self.db = db or get_database()
    
    def create_message(
        self,
        session_id: str,
        role: str,
        content: str,
        parent_message_id: Optional[str] = None,
        message_type: str = "text",
        model_params: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        创建新消息。
        
        Args:
            session_id: 会话ID
            role: 消息角色（user/assistant/system/tool）
            content: 消息内容
            parent_message_id: 父消息ID（构建对话树）
            message_type: 消息类型（text/image/file/tool_call）
            model_params: 模型参数（用于重放）
            metadata: 扩展元数据
            
        Returns:
            新创建的消息信息
        """
        message_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO messages 
                (message_id, session_id, parent_message_id, role, content, 
                 message_type, create_at, model_params, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    parent_message_id,
                    role,
                    content,
                    message_type,
                    now,
                    json.dumps(model_params or {}, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        
        logger.info(f"创建消息成功: message_id={message_id}, session_id={session_id}, role={role}")
        
        return {
            "message_id": message_id,
            "session_id": session_id,
            "parent_message_id": parent_message_id,
            "role": role,
            "content": content,
            "message_type": message_type,
            "create_at": now,
            "is_active": 1,
            "model_params": model_params or {},
            "metadata": metadata or {},
        }
    
    def get_message(self, message_id: str) -> Optional[dict[str, Any]]:
        """
        获取消息详情。
        
        Args:
            message_id: 消息ID
            
        Returns:
            消息信息，如果不存在返回None
        """
        row = self.db.fetch_one(
            """
            SELECT message_id, session_id, parent_message_id, role, content,
                   message_type, create_at, is_active, model_params, metadata
            FROM messages 
            WHERE message_id = ?
            """,
            (message_id,),
        )
        
        if row:
            row = self._parse_json_fields(row)
        
        return row
    
    def get_active_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        获取会话的活跃消息列表（按时间正序）。
        
        Args:
            session_id: 会话ID
            limit: 返回数量限制
            offset: 分页偏移量
            
        Returns:
            活跃消息列表
        """
        rows = self.db.fetch_all(
            """
            SELECT message_id, session_id, parent_message_id, role, content,
                   message_type, create_at, is_active, model_params, metadata
            FROM messages 
            WHERE session_id = ? AND is_active = 1
            ORDER BY create_at ASC
            LIMIT ? OFFSET ?
            """,
            (session_id, limit, offset),
        )
        
        return [self._parse_json_fields(row) for row in rows]
    
    def get_all_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        获取会话的所有消息（包括非活跃，按时间正序）。
        
        Args:
            session_id: 会话ID
            limit: 返回数量限制
            offset: 分页偏移量
            
        Returns:
            所有消息列表
        """
        rows = self.db.fetch_all(
            """
            SELECT message_id, session_id, parent_message_id, role, content,
                   message_type, create_at, is_active, model_params, metadata
            FROM messages 
            WHERE session_id = ?
            ORDER BY create_at ASC
            LIMIT ? OFFSET ?
            """,
            (session_id, limit, offset),
        )
        
        return [self._parse_json_fields(row) for row in rows]
    
    def get_message_chain(self, message_id: str) -> list[dict[str, Any]]:
        """
        获取从指定消息到根消息的完整链路（用于回溯）。
        
        Args:
            message_id: 消息ID
            
        Returns:
            从当前消息到根消息的链路
        """
        chain = []
        current_id = message_id
        
        while current_id:
            message = self.get_message(current_id)
            if not message:
                break
            chain.append(message)
            current_id = message.get("parent_message_id")
        
        return chain
    
    def get_branch_messages(
        self,
        session_id: str,
        start_message_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        获取从指定消息开始的分支消息（用于撤销操作）。
        
        Args:
            session_id: 会话ID
            start_message_id: 起始消息ID（不包含此消息）
            
        Returns:
            分支消息列表
        """
        if not start_message_id:
            return []
        
        # 获取起始消息的创建时间
        start_message = self.get_message(start_message_id)
        if not start_message:
            return []
        
        start_time = start_message["create_at"]
        
        # 获取所有在起始消息之后创建的消息
        rows = self.db.fetch_all(
            """
            SELECT message_id, session_id, parent_message_id, role, content,
                   message_type, create_at, is_active, model_params, metadata
            FROM messages 
            WHERE session_id = ? AND create_at > ?
            ORDER BY create_at ASC
            """,
            (session_id, start_time),
        )
        
        return [self._parse_json_fields(row) for row in rows]
    
    def deactivate_messages_after(self, session_id: str, message_id: str) -> int:
        """
        将指定消息之后的所有同分支消息标记为非活跃（用于撤销）。
        
        Args:
            session_id: 会话ID
            message_id: 消息ID
            
        Returns:
            被标记为非活跃的消息数量
        """
        branch_messages = self.get_branch_messages(session_id, message_id)
        
        if not branch_messages:
            return 0
        
        count = 0
        with self.db.transaction() as conn:
            for msg in branch_messages:
                if msg["is_active"] == 1:
                    cursor = conn.execute(
                        "UPDATE messages SET is_active = 0 WHERE message_id = ?",
                        (msg["message_id"],),
                    )
                    count += cursor.rowcount
        
        logger.info(f"撤销操作: 标记 {count} 条消息为非活跃, session_id={session_id}")
        return count
    
    def update_message(
        self,
        message_id: str,
        content: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        更新消息内容。
        
        Args:
            message_id: 消息ID
            content: 新内容（可选）
            metadata: 新元数据（可选）
            
        Returns:
            更新后的消息信息
        """
        update_fields = []
        params = []
        
        if content is not None:
            update_fields.append("content = ?")
            params.append(content)
        
        if metadata is not None:
            update_fields.append("metadata = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))
        
        if not update_fields:
            return self.get_message(message_id)
        
        params.append(message_id)
        
        with self.db.transaction() as conn:
            conn.execute(
                f"""
                UPDATE messages 
                SET {', '.join(update_fields)}
                WHERE message_id = ?
                """,
                tuple(params),
            )
        
        return self.get_message(message_id)
    
    def delete_message(self, message_id: str, hard_delete: bool = False) -> bool:
        """
        删除消息。
        
        Args:
            message_id: 消息ID
            hard_delete: 是否硬删除（默认软删除）
            
        Returns:
            是否删除成功
        """
        if hard_delete:
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    "DELETE FROM messages WHERE message_id = ?",
                    (message_id,),
                )
                return cursor.rowcount > 0
        else:
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    "UPDATE messages SET is_active = 0 WHERE message_id = ?",
                    (message_id,),
                )
                return cursor.rowcount > 0
    
    def get_last_message(self, session_id: str) -> Optional[dict[str, Any]]:
        """
        获取会话的最后一条活跃消息。
        
        Args:
            session_id: 会话ID
            
        Returns:
            最后一条消息，如果不存在返回None
        """
        row = self.db.fetch_one(
            """
            SELECT message_id, session_id, parent_message_id, role, content,
                   message_type, create_at, is_active, model_params, metadata
            FROM messages 
            WHERE session_id = ? AND is_active = 1
            ORDER BY create_at DESC
            LIMIT 1
            """,
            (session_id,),
        )
        
        if row:
            row = self._parse_json_fields(row)
        
        return row
    
    def get_message_count(self, session_id: str, is_active: int = 1) -> int:
        """
        获取会话消息数量。
        
        Args:
            session_id: 会话ID
            is_active: 消息状态过滤
            
        Returns:
            消息数量
        """
        row = self.db.fetch_one(
            "SELECT COUNT(*) as count FROM messages WHERE session_id = ? AND is_active = ?",
            (session_id, is_active),
        )
        return row["count"] if row else 0
    
    def _parse_json_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        """解析JSON字段。"""
        for field in ["model_params", "metadata"]:
            if row.get(field):
                try:
                    row[field] = json.loads(row[field])
                except (json.JSONDecodeError, TypeError):
                    row[field] = {}
        return row
