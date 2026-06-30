"""
Chat 相关 Schema。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """消息角色。"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """聊天消息。"""
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """聊天请求。"""
    message: str = Field(..., min_length=1, description="用户消息")
    agent_id: str = Field(default="design_review", description="目标 Agent ID")
    conversation_id: Optional[str] = Field(None, description="会话ID（可选）")
    session_id: Optional[str] = Field(None, description="会话ID（数据库关联）")
    file_paths: list[str] = Field(default_factory=list, description="上传的文件路径列表")
    image_urls: list[str] = Field(default_factory=list, description="图片URL列表")
    stream: bool = Field(default=True, description="是否使用流式响应")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """聊天响应（非流式）。"""
    message: str
    agent_id: str
    conversation_id: str
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    node_status: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class StreamEventType(str, Enum):
    """流式事件类型。"""
    MESSAGE = "message"              # 文本消息（打字机效果）
    TOOL_CALL = "tool_call"          # 工具调用
    TOOL_RESULT = "tool_result"      # 工具结果
    NODE_UPDATE = "node_update"      # 节点状态更新
    THINKING = "thinking"            # 思考中
    ERROR = "error"                  # 错误
    DONE = "done"                    # 完成


class StreamEvent(BaseModel):
    """
    流式事件 - 用于 SSE 推送。

    SSE 协议规范:
        - 标准字段: event, data, id, retry
        - agent_id / timestamp / sequence 由 to_sse_format() 自动放入 data JSON

    Attributes:
        event:    SSE event 类型
        data:     事件业务数据
        agent_id: 来源 Agent ID
        timestamp:事件时间戳
        sequence: 事件序号（同一任务内单调递增，便于客户端去重与顺序保证）
    """
    event: StreamEventType
    data: dict[str, Any]
    agent_id: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    sequence: int = 0

    def to_sse_format(self) -> str:
        """转换为 SSE 格式。
        """
        import enum as _enum
        import json
        if isinstance(self.event, _enum.Enum):
            event_name = self.event.value
        else:
            event_name = self.event
        # 将 agent_id / timestamp / sequence 放入 data 内部
        payload = {
            **self.data,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "sequence": self.sequence,
        }
        lines = []
        # 使用标准 event 字段
        lines.append(f"event: {event_name}")
        lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
        lines.append("")  # 空行结束事件
        lines.append("")  # 双换行
        return "\n".join(lines)


# ==================== 会话相关 Schema ====================

class CreateSessionRequest(BaseModel):
    """创建会话请求。"""
    user_id: str = Field(default="default_user", description="用户ID")
    session_title: Optional[str] = Field(None, description="会话标题")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SessionResponse(BaseModel):
    """会话响应。"""
    session_id: str
    user_id: str
    session_title: Optional[str] = None
    create_at: str
    update_at: str
    is_active: int = 1
    last_checkpoint_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    """会话列表响应。"""
    sessions: list[SessionResponse]
    total: int


class UpdateSessionRequest(BaseModel):
    """更新会话请求。"""
    session_title: Optional[str] = Field(None, description="新标题")
    is_active: Optional[int] = Field(None, description="会话状态")
    metadata: Optional[dict[str, Any]] = Field(None, description="扩展元数据")


# ==================== 消息相关 Schema ====================

class MessageResponse(BaseModel):
    """消息响应。"""
    message_id: str
    session_id: str
    parent_message_id: Optional[str] = None
    role: str
    content: str
    message_type: str = "text"
    create_at: str
    is_active: int = 1
    model_params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageListResponse(BaseModel):
    """消息列表响应。"""
    messages: list[MessageResponse]
    total: int


# ==================== 检查点相关 Schema ====================

class CheckpointResponse(BaseModel):
    """检查点响应。"""
    checkpoint_id: str
    session_id: str
    message_id: Optional[str] = None
    state_dump: Any = None
    create_at: str
    version: int
    trigger_type: str = "manual"
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CheckpointListResponse(BaseModel):
    """检查点列表响应。"""
    checkpoints: list[CheckpointResponse]
    total: int


class RollbackRequest(BaseModel):
    """回滚请求。"""
    checkpoint_id: str = Field(..., description="目标检查点ID")


# ==================== 撤销相关 Schema ====================

class UndoRequest(BaseModel):
    """撤销请求。"""
    message_id: str = Field(..., description="要撤销到的消息ID")
    session_id: str = Field(..., description="会话ID")


class UndoResponse(BaseModel):
    """撤销响应。"""
    success: bool
    checkpoint: Optional[CheckpointResponse] = None
    deactivated_count: int = 0
    message: str = ""


# ==================== 重放相关 Schema ====================

class ReplayRequest(BaseModel):
    """重放请求。"""
    message_id: str = Field(..., description="要重放的消息ID")
    session_id: str = Field(..., description="会话ID")
    agent_id: str = Field(default="design_review", description="目标 Agent ID")


class ReplayResponse(BaseModel):
    """重放响应。"""
    success: bool
    new_message: Optional[MessageResponse] = None
    message: str = ""
