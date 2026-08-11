"""
检查点服务模块。

提供检查点的CRUD操作，包括：
- 创建检查点
- 查询检查点
- 回滚到指定检查点
- 检查点版本管理
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from .database import Database, get_database

logger = logging.getLogger(__name__)


class CheckpointService:
    """检查点服务，管理对话状态快照。"""
    
    def __init__(self, db: Optional[Database] = None) -> None:
        """
        初始化检查点服务。
        
        Args:
            db: 数据库实例，如果不提供则使用默认实例
        """
        self.db = db or get_database()
    
    def create_checkpoint(
        self,
        session_id: str,
        state_dump: Any,
        message_id: Optional[str] = None,
        trigger_type: str = "manual",
        description: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        创建新检查点。
        
        Args:
            session_id: 会话ID
            state_dump: 状态快照数据（会被序列化为JSON存储）
            message_id: 关联的消息ID（可选）
            trigger_type: 触发类型（manual/auto_round/auto_error）
            description: 检查点描述
            metadata: 扩展元数据
            
        Returns:
            新创建的检查点信息
        """
        checkpoint_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        
        # 获取当前会话的最大版本号
        max_version = self._get_max_version(session_id)
        new_version = max_version + 1
        
        # 序列化状态数据
        state_dump_json = json.dumps(state_dump, ensure_ascii=False, default=str)
        
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints 
                (checkpoint_id, session_id, message_id, state_dump, create_at, 
                 version, trigger_type, description, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    session_id,
                    message_id,
                    state_dump_json,
                    now,
                    new_version,
                    trigger_type,
                    description,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        
        logger.info(
            f"创建检查点成功: checkpoint_id={checkpoint_id}, "
            f"session_id={session_id}, version={new_version}"
        )
        
        return {
            "checkpoint_id": checkpoint_id,
            "session_id": session_id,
            "message_id": message_id,
            "state_dump": state_dump,
            "create_at": now,
            "version": new_version,
            "trigger_type": trigger_type,
            "description": description,
            "metadata": metadata or {},
        }
    
    def get_checkpoint(self, checkpoint_id: str) -> Optional[dict[str, Any]]:
        """
        获取检查点详情。
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            检查点信息，如果不存在返回None
        """
        row = self.db.fetch_one(
            """
            SELECT checkpoint_id, session_id, message_id, state_dump, create_at,
                   version, trigger_type, description, metadata
            FROM checkpoints 
            WHERE checkpoint_id = ?
            """,
            (checkpoint_id,),
        )
        
        if row:
            row = self._parse_checkpoint(row)
        
        return row
    
    def get_session_checkpoints(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        获取会话的检查点列表（按版本号倒序）。
        
        Args:
            session_id: 会话ID
            limit: 返回数量限制
            offset: 分页偏移量
            
        Returns:
            检查点列表
        """
        rows = self.db.fetch_all(
            """
            SELECT checkpoint_id, session_id, message_id, state_dump, create_at,
                   version, trigger_type, description, metadata
            FROM checkpoints 
            WHERE session_id = ?
            ORDER BY version DESC
            LIMIT ? OFFSET ?
            """,
            (session_id, limit, offset),
        )
        
        return [self._parse_checkpoint(row) for row in rows]
    
    def get_latest_checkpoint(self, session_id: str) -> Optional[dict[str, Any]]:
        """
        获取会话的最新检查点。
        
        Args:
            session_id: 会话ID
            
        Returns:
            最新检查点，如果不存在返回None
        """
        row = self.db.fetch_one(
            """
            SELECT checkpoint_id, session_id, message_id, state_dump, create_at,
                   version, trigger_type, description, metadata
            FROM checkpoints 
            WHERE session_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (session_id,),
        )
        
        if row:
            row = self._parse_checkpoint(row)
        
        return row
    
    def get_checkpoint_by_message(self, message_id: str) -> Optional[dict[str, Any]]:
        """
        获取关联到指定消息的检查点。
        
        Args:
            message_id: 消息ID
            
        Returns:
            检查点信息，如果不存在返回None
        """
        row = self.db.fetch_one(
            """
            SELECT checkpoint_id, session_id, message_id, state_dump, create_at,
                   version, trigger_type, description, metadata
            FROM checkpoints 
            WHERE message_id = ?
            """,
            (message_id,),
        )
        
        if row:
            row = self._parse_checkpoint(row)
        
        return row
    
    def rollback_to_checkpoint(
        self,
        checkpoint_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        回滚到指定检查点。
        
        Args:
            checkpoint_id: 目标检查点ID
            
        Returns:
            回滚后的检查点信息，如果不存在返回None
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            logger.warning(f"检查点不存在: {checkpoint_id}")
            return None
        
        logger.info(
            f"回滚到检查点: checkpoint_id={checkpoint_id}, "
            f"session_id={checkpoint['session_id']}"
        )
        
        return checkpoint
    
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """
        删除检查点。
        
        Args:
            checkpoint_id: 检查点ID
            
        Returns:
            是否删除成功
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            )
            return cursor.rowcount > 0
    
    def delete_session_checkpoints(self, session_id: str) -> int:
        """
        删除会话的所有检查点。
        
        Args:
            session_id: 会话ID
            
        Returns:
            删除的检查点数量
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM checkpoints WHERE session_id = ?",
                (session_id,),
            )
            return cursor.rowcount
    
    def get_checkpoint_count(self, session_id: str) -> int:
        """
        获取会话检查点数量。
        
        Args:
            session_id: 会话ID
            
        Returns:
            检查点数量
        """
        row = self.db.fetch_one(
            "SELECT COUNT(*) as count FROM checkpoints WHERE session_id = ?",
            (session_id,),
        )
        return row["count"] if row else 0
    
    def create_initial_checkpoint(
        self,
        session_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """
        为新会话创建初始检查点。
        
        Args:
            session_id: 会话ID
            user_id: 用户ID
            
        Returns:
            新创建的检查点信息
        """
        initial_state = {
            "session_id": session_id,
            "user_id": user_id,
            "messages": [],
            "context": {},
            "created_at": datetime.now().isoformat(),
        }
        
        return self.create_checkpoint(
            session_id=session_id,
            state_dump=initial_state,
            trigger_type="auto_round",
            description="会话初始化检查点",
            metadata={"is_initial": True},
        )
    
    def _get_max_version(self, session_id: str) -> int:
        """获取会话的最大检查点版本号。"""
        row = self.db.fetch_one(
            "SELECT MAX(version) as max_version FROM checkpoints WHERE session_id = ?",
            (session_id,),
        )
        return row["max_version"] if row and row["max_version"] else 0
    
    def _parse_checkpoint(self, row: dict[str, Any]) -> dict[str, Any]:
        """解析检查点数据。"""
        # 解析JSON字段
        if row.get("state_dump"):
            try:
                row["state_dump"] = json.loads(row["state_dump"])
            except (json.JSONDecodeError, TypeError):
                row["state_dump"] = {}
        
        if row.get("metadata"):
            try:
                row["metadata"] = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                row["metadata"] = {}
        
        return row
