"""Middleware Core Module

Provides the core middleware abstractions and implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Generic, TypeVar, Optional, Union
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
        """Calculate elapsed time in milliseconds."""
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
    """Abstract base class for middleware.
    
    Middleware can intercept and modify agent behavior at various stages.
    """
    
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
        """Async middleware processing.
        
        Args:
            context: Middleware context
            state: Current state
            next_handler: Next handler in chain
            
        Returns:
            Processing result
        """
        if not self.enabled:
            return await next_handler()
        
        return await self._aprocess(context, state, next_handler)
    
    def process(
        self,
        context: MiddlewareContext,
        state: StateT,
        next_handler: Callable
    ) -> Any:
        """Sync middleware processing.
        
        Args:
            context: Middleware context
            state: Current state
            next_handler: Next handler in chain
            
        Returns:
            Processing result
        """
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
        """Override in subclasses for async processing."""
        pass
    
    def _process(
        self,
        context: MiddlewareContext,
        state: StateT,
        next_handler: Callable
    ) -> Any:
        """Override in subclasses for sync processing."""
        raise NotImplementedError("Either _aprocess or _process must be implemented")


class LoggingMiddleware(Middleware[Any]):
    """Middleware for logging node execution.
    
    Features:
    - Entry/exit logging
    - Timing information
    - State snapshots
    - Configurable log levels
    """
    
    def __init__(
        self,
        name: Optional[str] = None,
        log_level: int = logging.INFO,
        log_state: bool = False,
        log_timing: bool = True,
        logger: Optional[logging.Logger] = None,
        **kwargs
    ):
        super().__init__(name=name, **kwargs)
        self.log_level = log_level
        self.log_state = log_state
        self.log_timing = log_timing
        self.logger = logger or logging.getLogger(f"middleware.{name or 'logging'}")
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Log before and after handler execution."""
        node_name = context.node_name or 'unknown'
        
        self.logger.log(
            self.log_level,
            f"[{self.name}] Entering node: {node_name} "
            f"(thread: {context.thread_id}, elapsed: {context.elapsed_ms():.2f}ms)"
        )
        
        if self.log_state:
            state_snapshot = self._get_state_snapshot(state)
            self.logger.log(self.log_level, f"[{self.name}] State: {state_snapshot}")
        
        start_time = datetime.now()
        
        try:
            result = await next_handler()
            
            if self.log_timing:
                elapsed = (datetime.now() - start_time).total_seconds() * 1000
                self.logger.log(
                    self.log_level,
                    f"[{self.name}] Exiting node: {node_name} "
                    f"(duration: {elapsed:.2f}ms, success: True)"
                )
            
            return result
            
        except Exception as e:
            if self.log_timing:
                elapsed = (datetime.now() - start_time).total_seconds() * 1000
                self.logger.log(
                    logging.ERROR,
                    f"[{self.name}] Node failed: {node_name} "
                    f"(duration: {elapsed:.2f}ms, error: {str(e)})"
                )
            raise
    
    def _get_state_snapshot(self, state: Any) -> str:
        """Get a snapshot of the current state."""
        if hasattr(state, '__dict__'):
            try:
                import json
                return json.dumps(state, default=str, indent=2)[:500]
            except:
                return str(state)[:500]
        return str(state)[:500]


class ExceptionHandlerMiddleware(Middleware[Any]):
    """Middleware for handling exceptions in node execution.
    
    Features:
    - Custom exception handlers
    - Graceful degradation
    - Error logging
    - Retry logic
    """
    
    def __init__(
        self,
        name: Optional[str] = None,
        handlers: Optional[dict[type, Callable]] = None,
        log_errors: bool = True,
        reraise: bool = False,
        fallback_value: Any = None,
        **kwargs
    ):
        super().__init__(name=name, **kwargs)
        self.handlers = handlers or {}
        self.log_errors = log_errors
        self.reraise = reraise
        self.fallback_value = fallback_value
        self.logger = logging.getLogger(f"middleware.{name or 'exception'}")
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Handle exceptions from the next handler."""
        try:
            return await next_handler()
        except Exception as e:
            exception_type = type(e)
            
            if exception_type in self.handlers:
                handler = self.handlers[exception_type]
                try:
                    return await handler(e, context, state)
                except Exception as handler_error:
                    if self.log_errors:
                        self._log_error(handler_error, context)
                    if self.reraise:
                        raise handler_error
                    return self.fallback_value
            
            if self.log_errors:
                self._log_error(e, context)
            
            if self.reraise:
                raise
            
            return self.fallback_value
    
    def _log_error(self, error: Exception, context: MiddlewareContext) -> None:
        """Log error with context."""
        self.logger.error(
            f"[{self.name}] Exception in node {context.node_name}: {str(error)}\n"
            f"Traceback: {traceback.format_exc()}"
        )


class MiddlewareChain(Generic[StateT]):
    """Chain of middleware for processing.
    
    Features:
    - Ordered middleware execution
    - State propagation
    - Error handling
    - Hot-swapping
    """
    
    def __init__(self, middlewares: Optional[list[Middleware]] = None):
        self._middlewares: list[Middleware] = []
        if middlewares:
            for mw in middlewares:
                self.add(mw)
    
    def add(self, middleware: Middleware, order: Optional[MiddlewareOrder] = None) -> 'MiddlewareChain':
        """Add middleware to the chain.
        
        Args:
            middleware: Middleware to add
            order: Optional order override
            
        Returns:
            Self for chaining
        """
        if order:
            middleware = self._create_ordered_middleware(middleware, order)
        
        self._middlewares.append(middleware)
        self._middlewares.sort(key=lambda m: m.order.value)
        return self
    
    def _create_ordered_middleware(
        self,
        middleware: Middleware,
        order: MiddlewareOrder
    ) -> Middleware:
        """Create a copy of middleware with different order."""
        new_mw = type(middleware)()
        new_mw.name = middleware.name
        new_mw.enabled = middleware.enabled
        new_mw.order = order
        for attr in dir(middleware):
            if not attr.startswith('_') and hasattr(new_mw, attr):
                try:
                    setattr(new_mw, attr, getattr(middleware, attr))
                except:
                    pass
        return new_mw
    
    def remove(self, name: str) -> bool:
        """Remove middleware by name.
        
        Args:
            name: Middleware name
            
        Returns:
            True if removed
        """
        for i, mw in enumerate(self._middlewares):
            if mw.name == name:
                del self._middlewares[i]
                return True
        return False
    
    def get(self, name: str) -> Optional[Middleware]:
        """Get middleware by name.
        
        Args:
            name: Middleware name
            
        Returns:
            Middleware or None
        """
        for mw in self._middlewares:
            if mw.name == name:
                return mw
        return None
    
    def enable(self, name: str) -> bool:
        """Enable middleware by name.
        
        Args:
            name: Middleware name
            
        Returns:
            True if enabled
        """
        mw = self.get(name)
        if mw:
            mw.enabled = True
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """Disable middleware by name.
        
        Args:
            name: Middleware name
            
        Returns:
            True if disabled
        """
        mw = self.get(name)
        if mw:
            mw.enabled = False
            return True
        return False
    
    async def execute(
        self,
        context: MiddlewareContext,
        state: StateT,
        final_handler: Callable
    ) -> Any:
        """Execute the middleware chain.
        
        Args:
            context: Middleware context
            state: Current state
            final_handler: Final handler to execute
            
        Returns:
            Result from chain
        """
        async def build_chain(index: int) -> Callable:
            if index >= len(self._middlewares):
                return final_handler
            
            middleware = self._middlewares[index]
            next_handler = await build_chain(index + 1)
            
            async def wrapped_handler() -> Any:
                return await middleware.aprocess(context, state, next_handler)
            
            return wrapped_handler
        
        chain = await build_chain(0)
        return await chain()
    
    def execute_sync(
        self,
        context: MiddlewareContext,
        state: StateT,
        final_handler: Callable
    ) -> Any:
        """Synchronously execute the middleware chain.
        
        Args:
            context: Middleware context
            state: Current state
            final_handler: Final handler to execute
            
        Returns:
            Result from chain
        """
        def build_chain(index: int) -> Callable:
            if index >= len(self._middlewares):
                return final_handler
            
            middleware = self._middlewares[index]
            next_handler = build_chain(index + 1)
            
            def wrapped_handler() -> Any:
                return middleware.process(context, state, next_handler)
            
            return wrapped_handler
        
        chain = build_chain(0)
        return chain()


class ConditionalMiddleware(Middleware[Any]):
    """Middleware that only runs when a condition is met."""
    
    def __init__(
        self,
        condition: Callable[[MiddlewareContext, Any], bool],
        inner: Middleware,
        name: Optional[str] = None,
        **kwargs
    ):
        super().__init__(name=name or f"conditional_{inner.name}", **kwargs)
        self.condition = condition
        self.inner = inner
    
    async def _aprocess(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Execute inner middleware only if condition is true."""
        if self.condition(context, state):
            return await self.inner.aprocess(context, state, next_handler)
        return await next_handler()
    
    def _process(
        self,
        context: MiddlewareContext,
        state: Any,
        next_handler: Callable
    ) -> Any:
        """Sync version of conditional execution."""
        if self.condition(context, state):
            return self.inner.process(context, state, next_handler)
        return next_handler()