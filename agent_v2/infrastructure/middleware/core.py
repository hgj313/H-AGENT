"""Middleware Core Module

Provides the core middleware abstractions and implementations.
Following the architecture: Middleware = interception layer

Features:
- Middleware chain execution
- Request/response interception
- Logging and monitoring
- Rate limiting
- Authentication
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Generic, TypeVar, Optional, Union, TYPE_CHECKING
from datetime import datetime
import logging
import traceback


StateT = TypeVar('StateT')
ContextT = TypeVar('ContextT')


class MiddlewareOrder(Enum):
    BEFORE_ALL = auto()
    EARLY = auto()
    NORMAL = auto()
    LATE = auto()
    AFTER_ALL = auto()


@dataclass
class MiddlewareContext:
    graph_name: str
    node_name: Optional[str] = None
    thread_id: Optional[str] = None
    run_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    
    def elapsed_ms(self) -> float:
        return (datetime.now() - self.start_time).total_seconds() * 1000


@dataclass
class MiddlewareResult:
    success: bool
    data: Any = None
    error: Optional[str] = None
    modified_state: Optional[Any] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def success_result(cls, data: Any = None, **metadata) -> 'MiddlewareResult':
        return cls(success=True, data=data, metadata=metadata)
    
    @classmethod
    def error_result(cls, error: str, **metadata) -> 'MiddlewareResult':
        return cls(success=False, error=error, metadata=metadata)


class Middleware(ABC, Generic[StateT]):
    def __init__(
        self,
        name: Optional[str] = None,
        order: MiddlewareOrder = MiddlewareOrder.NORMAL,
        enabled: bool = True
    ):
        self.name = name or self.__class__.__name__
        self.order = order
        self.enabled = enabled
    
    async def aprocess(
        self,
        context: MiddlewareContext,
        state: StateT,
        next_handler: Callable
    ) -> Any:
        if not self.enabled:
            return await next_handler()
        return await self._aprocess(context, state, next_handler)
    
    def process(
        self,
        context: MiddlewareContext,
        state: StateT,
        next_handler: Callable
    ) -> Any:
        if not self.enabled:
            return next_handler()
        return self._process(context, state, next_handler)
    
    @abstractmethod
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: StateT,
        next_handler: Callable
    ) -> Any:
        pass
    
    def _process(
        self,
        context: MiddlewareContext,
        state: StateT,
        next_handler: Callable
    ) -> Any:
        raise NotImplementedError("Either _aprocess or _process must be implemented")


class MiddlewareChain:
    def __init__(self):
        self._middlewares: list[tuple[Middleware, MiddlewareOrder]] = []
    
    def add(self, middleware: Middleware) -> 'MiddlewareChain':
        self._middlewares.append((middleware, middleware.order))
        self._middlewares.sort(key=lambda x: x[1].value)
        return self
    
    def remove(self, name: str) -> bool:
        original_len = len(self._middlewares)
        self._middlewares = [
            (m, o) for m, o in self._middlewares
            if m.name != name
        ]
        return len(self._middlewares) < original_len
    
    async def execute(self, context: MiddlewareContext, state: Any, handler: Callable) -> Any:
        async def next_handler():
            return handler()
        
        for middleware, _ in self._middlewares:
            if not middleware.enabled:
                continue
            
            next_fn = next_handler
            
            async def wrapped_handler():
                return await middleware.aprocess(context, state, next_fn)
            
            next_handler = wrapped_handler
        
        return await next_handler()
    
    def execute_sync(self, context: MiddlewareContext, state: Any, handler: Callable) -> Any:
        def next_handler():
            return handler()
        
        for middleware, _ in self._middlewares:
            if not middleware.enabled:
                continue
            
            next_fn = next_handler
            
            def wrapped_handler():
                return middleware.process(context, state, next_fn)
            
            next_handler = wrapped_handler
        
        return next_handler()
    
    def clear(self) -> None:
        self._middlewares.clear()
    
    def list_middlewares(self) -> list[str]:
        return [m.name for m, _ in self._middlewares]


class LoggingMiddleware(Middleware[Any]):
    def __init__(
        self,
        name: Optional[str] = None,
        log_level: int = logging.INFO,
        log_state: bool = False,
        log_timing: bool = True,
        **kwargs
    ):
        super().__init__(name=name or "logging", **kwargs)
        self.log_level = log_level
        self.log_state = log_state
        self.log_timing = log_timing
        self.logger = logging.getLogger(f"middleware.{self.name}")
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        node_name = context.node_name or "unknown"
        
        self.logger.log(
            self.log_level,
            f"[{node_name}] Starting execution"
        )
        
        start_time = datetime.now()
        
        try:
            result = await next_handler()
            
            if self.log_timing:
                elapsed = (datetime.now() - start_time).total_seconds() * 1000
                self.logger.log(
                    self.log_level,
                    f"[{node_name}] Completed in {elapsed:.2f}ms"
                )
            
            return result
            
        except Exception as e:
            self.logger.error(
                f"[{node_name}] Error: {str(e)}\n{traceback.format_exc()}"
            )
            raise


class TimingMiddleware(Middleware[Any]):
    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name or "timing", **kwargs)
        self.timings: dict[str, list[float]] = {}
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        node_name = context.node_name or "unknown"
        
        start_time = datetime.now()
        
        result = await next_handler()
        
        elapsed = (datetime.now() - start_time).total_seconds() * 1000
        
        if node_name not in self.timings:
            self.timings[node_name] = []
        
        self.timings[node_name].append(elapsed)
        
        if 'timing' not in context.metadata:
            context.metadata['timing'] = {}
        
        context.metadata['timing'][node_name] = elapsed
        
        return result
    
    def get_timings(self, node_name: Optional[str] = None) -> dict:
        if node_name:
            return {
                'node': node_name,
                'count': len(self.timings.get(node_name, [])),
                'total_ms': sum(self.timings.get(node_name, [])),
                'avg_ms': sum(self.timings.get(node_name, [])) / max(len(self.timings.get(node_name, [])), 1)
            }
        
        return {
            name: {
                'count': len(times),
                'total_ms': sum(times),
                'avg_ms': sum(times) / len(times) if times else 0
            }
            for name, times in self.timings.items()
        }


class ErrorHandlerMiddleware(Middleware[Any]):
    def __init__(
        self,
        name: Optional[str] = None,
        error_handler: Optional[Callable[[Exception, MiddlewareContext], Any]] = None,
        log_errors: bool = True,
        **kwargs
    ):
        super().__init__(name=name or "error_handler", **kwargs)
        self.error_handler = error_handler
        self.log_errors = log_errors
        self.logger = logging.getLogger(f"middleware.{self.name}")
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        try:
            return await next_handler()
        except Exception as e:
            if self.log_errors:
                self.logger.error(
                    f"Error in {context.node_name}: {str(e)}\n{traceback.format_exc()}"
                )
            
            if self.error_handler:
                return self.error_handler(e, context)
            
            raise