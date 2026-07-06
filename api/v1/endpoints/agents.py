"""
Agent 管理端点。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api.v1.schemas.agents import (
    AgentInfo,
    AgentListResponse,
    AgentActionRequest,
    AgentActionResponse,
    HealthCheckResponse,
    AgentConfigInfo,
    AgentStateInfo,
)
from core.registry.agent_registry import AgentRegistry
from core.agents.base import AgentStatus
from core.agents.exceptions import AgentNotFoundError, AgentStateError

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_registry(request: Request) -> AgentRegistry:
    """从 app state 获取 registry。"""
    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="AgentRegistry 未初始化")
    return registry


def _agent_to_info(agent) -> AgentInfo:
    """将 Agent 转换为 API 响应格式。"""
    config = agent.config
    state = agent.state
    return AgentInfo(
        config=AgentConfigInfo(
            agent_id=config.agent_id,
            name=config.name,
            description=config.description,
            agent_type=config.agent_type.value,
            version=config.version,
            capabilities=list(config.capabilities),
            max_concurrent=config.max_concurrent,
            timeout=config.timeout,
        ),
        state=AgentStateInfo(
            status=state.status.value,
            current_task_id=state.current_task_id,
            start_time=state.start_time,
            error_count=state.error_count,
            last_error=state.last_error,
            metrics=state.metrics,
        ),
        is_available=agent.is_available,
    )


@router.get("/", response_model=AgentListResponse)
async def list_agents(request: Request) -> AgentListResponse:
    """获取所有 Agent 列表。"""
    registry = _get_registry(request)
    agents = [_agent_to_info(agent) for agent in registry]
    available_count = sum(1 for a in agents if a.is_available)

    return AgentListResponse(
        agents=agents,
        total=len(agents),
        available_count=available_count,
    )


@router.get("/{agent_id}", response_model=AgentInfo)
async def get_agent(agent_id: str, request: Request) -> AgentInfo:
    """获取指定 Agent 信息。"""
    registry = _get_registry(request)
    agent = registry.get(agent_id)

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent 未找到: {agent_id}",
        )

    return _agent_to_info(agent)


@router.post("/{agent_id}/actions", response_model=AgentActionResponse)
async def agent_action(
    agent_id: str,
    action_request: AgentActionRequest,
    request: Request,
) -> AgentActionResponse:
    """
    执行 Agent 操作。

    支持的操作：
    - pause: 暂停 Agent
    - resume: 恢复 Agent
    - restart: 重启 Agent
    """
    registry = _get_registry(request)
    agent = registry.get(agent_id)

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent 未找到: {agent_id}",
        )

    action = action_request.action.lower()

    try:
        if action == "pause":
            if agent.state.status != AgentStatus.RUNNING:
                raise AgentStateError("只能暂停运行中的 Agent")
            registry.pause(agent_id)
            return AgentActionResponse(
                success=True,
                message=f"Agent {agent_id} 已暂停",
                agent_id=agent_id,
                new_status=AgentStatus.PAUSED.value,
            )

        elif action == "resume":
            if agent.state.status != AgentStatus.PAUSED:
                raise AgentStateError("只能恢复已暂停的 Agent")
            registry.resume(agent_id)
            return AgentActionResponse(
                success=True,
                message=f"Agent {agent_id} 已恢复",
                agent_id=agent_id,
                new_status=AgentStatus.IDLE.value,
            )

        elif action == "restart":
            # 重置 Agent 状态
            agent._state.reset()
            return AgentActionResponse(
                success=True,
                message=f"Agent {agent_id} 已重启",
                agent_id=agent_id,
                new_status=AgentStatus.IDLE.value,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的操作: {action}",
            )

    except AgentStateError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(request: Request) -> HealthCheckResponse:
    """系统健康检查。"""
    registry = _get_registry(request)
    health = registry.health_check()

    return HealthCheckResponse(**health)
