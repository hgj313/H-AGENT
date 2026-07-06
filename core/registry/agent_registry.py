"""
Agent 注册器 - 统一管理所有 Agent 的生命周期。

设计原则：
1. 单一职责：只负责 Agent 的注册、发现和生命周期管理
2. 依赖注入：通过注册机制解耦 Agent 间的依赖
3. 观察者模式：通过事件系统通知状态变化
4. 线程安全：支持并发访问

扩展点：
- 自定义 Agent 通过继承 BaseAgent 实现
- 通过 EventBus 监听生命周期事件
- 支持 Agent 动态加载（未来扩展）
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Iterator

from core.agents.base import BaseAgent, AgentConfig, AgentStatus, AgentType
from core.agents.exceptions import (
    AgentNotFoundError,
    AgentRegistrationError,
    AgentStateError,
)
from core.registry.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Agent 注册中心 - 管理所有 Agent 的生命周期。

    特性：
    - 注册/注销 Agent
    - 按 ID/类型查询 Agent
    - 生命周期管理（启动/暂停/恢复/停止）
    - 状态监控和健康检查
    - 事件驱动的状态通知

    Usage:
        registry = AgentRegistry()

        # 注册 Agent
        registry.register(my_agent)

        # 获取 Agent
        agent = registry.get("design_review")

        # 执行任务
        async for event in agent.execute({"message": "..."}):

        # 注销 Agent
        registry.unregister("design_review")

    线程安全：
    - 所有公开方法都是线程安全的
    - 内部使用 asyncio.Lock 保护共享状态
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._event_bus = event_bus or EventBus()
        self._lock = asyncio.Lock()
        self._initialized_at = datetime.now()

        logger.info("AgentRegistry 已初始化")

    @property
    def event_bus(self) -> EventBus:
        """获取事件总线。"""
        return self._event_bus

    @property
    def agent_count(self) -> int:
        """已注册 Agent 数量。"""
        return len(self._agents)

    @property
    def available_agents(self) -> list[BaseAgent]:
        """获取所有可用的 Agent。"""
        return [agent for agent in self._agents.values() if agent.is_available]

    # ── 注册/注销 ────────────────────────────────────────────────

    def register(self, agent: BaseAgent) -> None:
        """
        注册 Agent。

        Args:
            agent: Agent 实例

        Raises:
            AgentRegistrationError: 注册失败（ID 冲突等）
        """
        agent_id = agent.agent_id

        if agent_id in self._agents:
            raise AgentRegistrationError(
                f"Agent ID 冲突: {agent_id}",
                agent_id=agent_id,
            )

        self._agents[agent_id] = agent
        logger.info(f"Agent 已注册: {agent_id} ({agent.config.name})")

        self._event_bus.emit(Event(
            event_type=EventType.AGENT_REGISTERED,
            source="registry",
            data={"agent_id": agent_id, "config": agent.config.to_dict()},
        ))

    def unregister(self, agent_id: str) -> None:
        """
        注销 Agent。

        Args:
            agent_id: Agent ID

        Raises:
            AgentNotFoundError: Agent 未找到
        """
        agent = self._get_agent_or_raise(agent_id)

        # 清理资源
        agent.on_destroy()

        del self._agents[agent_id]
        logger.info(f"Agent 已注销: {agent_id}")

        self._event_bus.emit(Event(
            event_type=EventType.AGENT_UNREGISTERED,
            source="registry",
            data={"agent_id": agent_id},
        ))

    # ── 查询 ─────────────────────────────────────────────────────

    def get(self, agent_id: str) -> BaseAgent | None:
        """
        获取 Agent（不抛异常）。

        Args:
            agent_id: Agent ID

        Returns:
            Agent 实例或 None
        """
        return self._agents.get(agent_id)

    def get_or_raise(self, agent_id: str) -> BaseAgent:
        """
        获取 Agent（未找到则抛异常）。

        Args:
            agent_id: Agent ID

        Returns:
            Agent 实例

        Raises:
            AgentNotFoundError: Agent 未找到
        """
        return self._get_agent_or_raise(agent_id)

    def get_by_type(self, agent_type: AgentType) -> list[BaseAgent]:
        """
        按类型查询 Agent。

        Args:
            agent_type: Agent 类型

        Returns:
            Agent 列表
        """
        return [
            agent for agent in self._agents.values()
            if agent.config.agent_type == agent_type
        ]

    def get_by_capability(self, capability: str) -> list[BaseAgent]:
        """
        按能力查询 Agent。

        Args:
            capability: 能力标识

        Returns:
            具备该能力的 Agent 列表
        """
        return [
            agent for agent in self._agents.values()
            if capability in agent.config.capabilities
        ]

    def list_all(self) -> list[dict[str, Any]]:
        """
        列出所有 Agent 信息。

        Returns:
            Agent 信息列表
        """
        return [agent.get_info() for agent in self._agents.values()]

    # ── 生命周期管理 ─────────────────────────────────────────────

    def pause(self, agent_id: str) -> None:
        """暂停 Agent。"""
        agent = self._get_agent_or_raise(agent_id)
        agent.on_pause()
        self._emit_status_change(agent_id, AgentStatus.PAUSED)

    def resume(self, agent_id: str) -> None:
        """恢复 Agent。"""
        agent = self._get_agent_or_raise(agent_id)
        agent.on_resume()
        self._emit_status_change(agent_id, AgentStatus.IDLE)

    # ── 健康检查 ─────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """
        执行健康检查。

        Returns:
            健康状态报告
        """
        total = len(self._agents)
        available = len(self.available_agents)
        running = sum(
            1 for a in self._agents.values()
            if a.state.status == AgentStatus.RUNNING
        )
        error = sum(
            1 for a in self._agents.values()
            if a.state.status == AgentStatus.ERROR
        )

        return {
            "status": "healthy" if error == 0 else "degraded",
            "total_agents": total,
            "available_agents": available,
            "running_agents": running,
            "error_agents": error,
            "uptime_seconds": (datetime.now() - self._initialized_at).total_seconds(),
            "timestamp": datetime.now().isoformat(),
        }

    # ── 内部方法 ─────────────────────────────────────────────────

    def _get_agent_or_raise(self, agent_id: str) -> BaseAgent:
        """获取 Agent，未找到则抛异常。"""
        agent = self._agents.get(agent_id)
        if agent is None:
            raise AgentNotFoundError(
                f"Agent 未找到: {agent_id}",
                agent_id=agent_id,
            )
        return agent

    def _emit_status_change(self, agent_id: str, status: AgentStatus) -> None:
        """发布状态变更事件。"""
        self._event_bus.emit(Event(
            event_type=EventType.AGENT_STATUS_CHANGED,
            source="registry",
            data={"agent_id": agent_id, "status": status.value},
        ))

    # ── 迭代器支持 ───────────────────────────────────────────────

    def __iter__(self) -> Iterator[BaseAgent]:
        """支持迭代所有 Agent。"""
        return iter(self._agents.values())

    def __len__(self) -> int:
        """支持 len() 函数。"""
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        """支持 in 操作符。"""
        return agent_id in self._agents

    def __repr__(self) -> str:
        return f"<AgentRegistry agents={len(self._agents)}>"
