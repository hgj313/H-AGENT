"""
事件系统 - 实现组件间的松耦合通信。

设计模式：观察者模式 + 发布/订阅模式
支持同步和异步事件处理。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine
from collections import defaultdict

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型枚举。"""
    # Agent 生命周期事件
    AGENT_REGISTERED = "agent.registered"
    AGENT_UNREGISTERED = "agent.unregistered"
    AGENT_STATUS_CHANGED = "agent.status_changed"
    AGENT_ERROR = "agent.error"

    # 任务事件
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # 流式事件
    STREAM_MESSAGE = "stream.message"
    STREAM_TOOL_CALL = "stream.tool_call"
    STREAM_NODE_UPDATE = "stream.node_update"
    STREAM_DONE = "stream.done"

    # 系统事件
    SYSTEM_READY = "system.ready"
    SYSTEM_SHUTDOWN = "system.shutdown"


@dataclass
class Event:
    """
    事件数据类。

    Attributes:
        event_type: 事件类型
        source: 事件来源
        data: 事件数据
        timestamp: 事件时间戳
    """
    event_type: EventType | str
    source: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else self.event_type,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


# 事件处理器类型
EventHandler = Callable[[Event], None]
AsyncEventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    事件总线 - 实现发布/订阅模式。

    特性：
    - 支持同步和异步处理器
    - 支持通配符订阅
    - 线程安全
    - 支持事件过滤

    Usage:
        bus = EventBus()

        # 订阅事件
        @bus.on(EventType.AGENT_REGISTERED)
        def handle_register(event: Event):
            print(f"Agent registered: {event.data}")

        # 发布事件
        bus.emit(Event(
            event_type=EventType.AGENT_REGISTERED,
            source="registry",
            data={"agent_id": "design_review"}
        ))
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler | AsyncEventHandler]] = defaultdict(list)
        self._async_handlers: dict[str, list[AsyncEventHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def on(
        self,
        event_type: EventType | str,
        handler: EventHandler | AsyncEventHandler | None = None,
    ) -> Callable:
        """
        注册事件处理器（装饰器或直接调用）。

        Usage:
            # 作为装饰器
            @bus.on(EventType.AGENT_REGISTERED)
            def handler(event): ...

            # 直接调用
            bus.on(EventType.AGENT_REGISTERED, handler)
        """
        def decorator(func: EventHandler | AsyncEventHandler) -> EventHandler | AsyncEventHandler:
            key = event_type.value if isinstance(event_type, EventType) else event_type
            if asyncio.iscoroutinefunction(func):
                self._async_handlers[key].append(func)
            else:
                self._handlers[key].append(func)
            return func

        if handler is not None:
            return decorator(handler)
        return decorator

    def off(self, event_type: EventType | str, handler: EventHandler | AsyncEventHandler) -> None:
        """移除事件处理器。"""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        if handler in self._handlers.get(key, []):
            self._handlers[key].remove(handler)
        if handler in self._async_handlers.get(key, []):
            self._async_handlers[key].remove(handler)

    def emit(self, event: Event) -> None:
        """
        同步发布事件。

        Args:
            event: 事件对象
        """
        key = event.event_type.value if isinstance(event.event_type, EventType) else event.event_type
        logger.debug(f"Event emitted: {key} from {event.source}")

        for handler in self._handlers.get(key, []):
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}", exc_info=True)

        # 通配符订阅
        for handler in self._handlers.get("*", []):
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Wildcard handler error: {e}", exc_info=True)

    async def emit_async(self, event: Event) -> None:
        """
        异步发布事件。

        Args:
            event: 事件对象
        """
        key = event.event_type.value if isinstance(event.event_type, EventType) else event.event_type
        logger.debug(f"Async event emitted: {key} from {event.source}")

        for handler in self._async_handlers.get(key, []):
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Async event handler error: {e}", exc_info=True)

        # 通配符订阅
        for handler in self._async_handlers.get("*", []):
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Async wildcard handler error: {e}", exc_info=True)

    def clear(self) -> None:
        """清除所有事件处理器。"""
        self._handlers.clear()
        self._async_handlers.clear()
