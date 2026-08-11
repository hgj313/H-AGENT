"""
Agent 抽象基类 - 定义所有 Agent 必须实现的接口。

设计原则：
1. 单一职责：每个 Agent 专注一个领域
2. 依赖倒置：依赖抽象而非具体实现
3. 开闭原则：对扩展开放，对修改关闭
4. 接口隔离：精简的公共接口
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Agent 类型枚举，便于分类管理和路由。"""
    DESIGN_REVIEW = "design_review"
    CODE_REVIEW = "code_review"
    DOCUMENT = "document"
    CUSTOM = "custom"


class AgentStatus(str, Enum):
    """Agent 生命周期状态。"""
    IDLE = "idle"              # 空闲，可接受任务
    RUNNING = "running"        # 正在执行任务
    PAUSED = "paused"          # 已暂停
    ERROR = "error"            # 发生错误
    DISABLED = "disabled"      # 已禁用


@dataclass(frozen=True)
class AgentConfig:
    """
    Agent 配置 - 不可变数据类，确保配置一致性。

    Attributes:
        agent_id: 唯一标识符
        name: 显示名称
        description: 功能描述
        agent_type: Agent 类型
        version: 版本号
        capabilities: 支持的能力列表
        max_concurrent: 最大并发任务数
        timeout: 任务超时时间(秒)
        metadata: 扩展元数据
    """
    agent_id: str
    name: str
    description: str = ""
    agent_type: AgentType = AgentType.CUSTOM
    version: str = "1.0.0"
    capabilities: tuple[str, ...] = ()
    max_concurrent: int = 1
    timeout: float = 300.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "agent_type": self.agent_type.value,
            "version": self.version,
            "capabilities": list(self.capabilities),
            "max_concurrent": self.max_concurrent,
            "timeout": self.timeout,
            "metadata": self.metadata,
        }


@dataclass
class AgentState:
    """
    Agent 运行时状态 - 可变状态容器。

    Attributes:
        status: 当前状态
        current_task_id: 当前任务ID
        start_time: 任务开始时间
        error_count: 错误计数
        last_error: 最后一次错误信息
        metrics: 运行指标
    """
    status: AgentStatus = AgentStatus.IDLE
    current_task_id: str | None = None
    start_time: datetime | None = None
    error_count: int = 0
    last_error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        """重置状态为空闲。"""
        self.status = AgentStatus.IDLE
        self.current_task_id = None
        self.start_time = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "status": self.status.value,
            "current_task_id": self.current_task_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "metrics": self.metrics,
        }


@dataclass
class StreamEvent:
    """
    流式事件 - 用于 SSE 推送。

    SSE 协议规范:
        - 标准字段: event, data, id, retry
        - 非标准字段会被浏览器忽略

    使用方式:
        # 创建事件时，agent_id 作为顶层参数（便于内部使用）
        event = StreamEvent(
            event="message",
            data={"content": "hello"},
            agent_id="my_agent"
        )

        # 转换为 SSE 格式时，to_sse_format() 会自动将 agent_id、timestamp、sequence 放入 data JSON
        sse_str = event.to_sse_format()
        # 输出:
        # event: message
        # data: {"content": "hello", "agent_id": "my_agent", "timestamp": "2026-06-08T12:00:00", "sequence": 1}

    Attributes:
        event:   SSE event 类型 (message/tool_call/node_update/error/done/thinking/...)
        data:    事件业务数据（不含 agent_id、timestamp、sequence，它们会由 to_sse_format() 自动添加）
        agent_id: 来源 Agent ID（内部使用，to_sse_format() 会放入 data）
        timestamp: 事件时间戳（内部使用，to_sse_format() 会放入 data）
        sequence: 事件序号（同一任务内单调递增，便于客户端去重与顺序保证）
    """
    event: str
    data: dict[str, Any]
    agent_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    sequence: int = 0

    def to_sse_format(self) -> str:
        """
        转换为 SSE 格式。
        """
        import enum as _enum
        import json
        # 兼容 self.event 为 str 或 StreamEventType enum：
        # - (str, Enum) 混入 → isinstance(str) 也为 True，但 __str__ 是 name；要 .value
        # - 纯 str       → 直接使用
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


class BaseAgent(ABC):
    """
    Agent 抽象基类 - 所有 Agent 的根接口。

    子类必须实现:
        - config: 返回 AgentConfig
        - execute(): 执行任务并返回流式事件
        - validate_input(): 验证输入参数

    可选重写:
        - on_init(): 初始化钩子
        - on_destroy(): 销毁钩子
        - on_pause(): 暂停钩子
        - on_resume(): 恢复钩子
    """

    def __init__(self) -> None:
        self._state = AgentState()
        self._logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
        self.on_init()

    @property
    @abstractmethod
    def config(self) -> AgentConfig:
        """返回 Agent 配置（不可变）。"""
        ...

    @property
    def state(self) -> AgentState:
        """返回当前运行状态。"""
        return self._state

    @property
    def agent_id(self) -> str:
        """快捷访问 agent_id。"""
        return self.config.agent_id

    @property
    def is_available(self) -> bool:
        """是否可接受新任务。"""
        return (
            self._state.status == AgentStatus.IDLE
            and self._state.error_count < 3  # 连续错误阈值
        )

    @abstractmethod
    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str | None]:
        """
        验证输入参数。

        Args:
            input_data: 输入数据

        Returns:
            (is_valid, error_message) 元组
        """
        ...

    @abstractmethod
    async def execute(
        self,
        input_data: dict[str, Any],
        task_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        执行任务并返回流式事件。

        Args:
            input_data: 输入数据
            task_id: 任务ID（可选，自动生成）

        Yields:
            StreamEvent: 流式事件

        Raises:
            AgentError: 执行错误
        """
        ...

    # ── 生命周期钩子 ─────────────────────────────────────────────

    def on_init(self) -> None:
        """初始化钩子，子类可重写。"""
        self._logger.info(f"Agent [{self.agent_id}] 已初始化")

    def on_destroy(self) -> None:
        """销毁钩子，子类可重写。"""
        self._logger.info(f"Agent [{self.agent_id}] 已销毁")

    def on_pause(self) -> None:
        """暂停钩子，子类可重写。"""
        self._state.status = AgentStatus.PAUSED
        self._logger.info(f"Agent [{self.agent_id}] 已暂停")

    def on_resume(self) -> None:
        """恢复钩子，子类可重写。"""
        self._state.status = AgentStatus.IDLE
        self._logger.info(f"Agent [{self.agent_id}] 已恢复")

    # ── 状态管理 ─────────────────────────────────────────────────

    def _start_task(self, task_id: str) -> None:
        """标记任务开始。"""
        self._state.status = AgentStatus.RUNNING
        self._state.current_task_id = task_id
        self._state.start_time = datetime.now()
        self._logger.info(f"Agent [{self.agent_id}] 开始任务: {task_id}")

    def _complete_task(self) -> None:
        """标记任务完成。"""
        self._state.reset()
        self._logger.info(f"Agent [{self.agent_id}] 任务完成")

    def _fail_task(self, error: str) -> None:
        """标记任务失败。"""
        self._state.status = AgentStatus.ERROR
        self._state.last_error = error
        self._state.error_count += 1
        self._logger.error(f"Agent [{self.agent_id}] 任务失败: {error}")

    def get_info(self) -> dict[str, Any]:
        """获取 Agent 完整信息。"""
        return {
            "config": self.config.to_dict(),
            "state": self._state.to_dict(),
            "is_available": self.is_available,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.agent_id} status={self._state.status.value}>"
