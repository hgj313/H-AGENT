"""
Agent 相关 Schema。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class AgentConfigInfo(BaseModel):
    """Agent 配置信息。"""
    agent_id: str
    name: str
    description: str = ""
    agent_type: str = "custom"
    version: str = "1.0.0"
    capabilities: list[str] = Field(default_factory=list)
    max_concurrent: int = 1
    timeout: float = 300.0


class AgentStateInfo(BaseModel):
    """Agent 状态信息。"""
    status: str = "idle"
    current_task_id: Optional[str] = None
    start_time: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class AgentInfo(BaseModel):
    """Agent 完整信息。"""
    config: AgentConfigInfo
    state: AgentStateInfo
    is_available: bool = True


class AgentListResponse(BaseModel):
    """Agent 列表响应。"""
    agents: list[AgentInfo]
    total: int
    available_count: int


class AgentActionRequest(BaseModel):
    """Agent 操作请求。"""
    action: str = Field(..., description="操作类型: pause/resume/restart")
    agent_id: str = Field(..., description="目标 Agent ID")


class AgentActionResponse(BaseModel):
    """Agent 操作响应。"""
    success: bool
    message: str
    agent_id: str
    new_status: Optional[str] = None


class HealthCheckResponse(BaseModel):
    """健康检查响应。"""
    status: str
    total_agents: int
    available_agents: int
    running_agents: int
    error_agents: int
    uptime_seconds: float
    timestamp: datetime
