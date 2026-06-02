"""Middleware Manager Module

Manages middleware configuration, lifecycle, and integration with LangGraph.
"""

from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum
import threading

from .core import (
    Middleware,
    MiddlewareChain,
    MiddlewareContext,
    MiddlewareOrder,
)


class IntegrationMode(Enum):
    NODE_WRAPPER = "node_wrapper"
    GRAPH_INJECTION = "graph_injection"
    CHECKPOINT = "checkpoint"


@dataclass
class MiddlewareConfig:
    name: str
    middleware_class: type[Middleware]
    order: MiddlewareOrder = MiddlewareOrder.NORMAL
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    nodes: Optional[list[str]] = None


class MiddlewareManager:
    """Manages middleware lifecycle and integration with LangGraph.
    
    Features:
    - Middleware registration and configuration
    - Lifecycle management
    - Node-specific middleware
    - Hot-swapping
    - Integration with LangGraph
    """
    
    def __init__(self):
        self._configurations: dict[str, MiddlewareConfig] = {}
        self._chains: dict[str, MiddlewareChain] = {}
        self._node_chains: dict[str, MiddlewareChain] = {}
        self._lock = threading.RLock()
    
    def configure(self, config: MiddlewareConfig) -> None:
        """Configure a middleware.
        
        Args:
            config: Middleware configuration
        """
        with self._lock:
            self._configurations[config.name] = config
    
    def register(
        self,
        name: str,
        middleware: Middleware,
        nodes: Optional[list[str]] = None
    ) -> None:
        """Register a middleware instance.
        
        Args:
            name: Middleware name
            middleware: Middleware instance
            nodes: Optional list of nodes this middleware applies to
        """
        with self._lock:
            config = MiddlewareConfig(
                name=name,
                middleware_class=type(middleware),
                config={},
                nodes=nodes
            )
            config.order = middleware.order
            config.enabled = middleware.enabled
            
            self._configurations[name] = config
            
            if nodes:
                for node in nodes:
                    if node not in self._node_chains:
                        self._node_chains[node] = MiddlewareChain()
                    self._node_chains[node].add(middleware)
            else:
                if name not in self._chains:
                    self._chains[name] = MiddlewareChain()
                self._chains[name].add(middleware)
    
    def unregister(self, name: str) -> bool:
        """Unregister a middleware.
        
        Args:
            name: Middleware name
            
        Returns:
            True if unregistered
        """
        with self._lock:
            if name in self._configurations:
                del self._configurations[name]
            
            if name in self._chains:
                self._chains[name].remove(name)
            
            for node_chains in self._node_chains.values():
                node_chains.remove(name)
            
            return True
        return False
    
    def get_chain(self, name: str) -> Optional[MiddlewareChain]:
        """Get middleware chain by name.
        
        Args:
            name: Chain name
            
        Returns:
            MiddlewareChain or None
        """
        return self._chains.get(name)
    
    def get_node_chain(self, node_name: str) -> Optional[MiddlewareChain]:
        """Get middleware chain for a specific node.
        
        Args:
            node_name: Node name
            
        Returns:
            MiddlewareChain or None
        """
        return self._node_chains.get(node_name)
    
    def execute_node(
        self,
        node_name: str,
        context: MiddlewareContext,
        state: Any,
        handler: Callable
    ) -> Any:
        """Execute a node with its middleware chain.
        
        Args:
            node_name: Node name
            context: Middleware context
            state: Current state
            handler: Node handler
            
        Returns:
            Execution result
        """
        chain = self._node_chains.get(node_name)
        if chain:
            import asyncio
            if asyncio.iscoroutinefunction(handler):
                return chain.execute(context, state, handler)
            else:
                return chain.execute_sync(context, state, handler)
        return handler()
    
    def enable(self, name: str) -> bool:
        """Enable a middleware.
        
        Args:
            name: Middleware name
            
        Returns:
            True if enabled
        """
        with self._lock:
            config = self._configurations.get(name)
            if config:
                config.enabled = True
                return True
        return False
    
    def disable(self, name: str) -> bool:
        """Disable a middleware.
        
        Args:
            name: Middleware name
            
        Returns:
            True if disabled
        """
        with self._lock:
            config = self._configurations.get(name)
            if config:
                config.enabled = False
                return True
        return False
    
    def list_middlewares(self) -> list[MiddlewareConfig]:
        """List all configured middlewares.
        
        Returns:
            List of MiddlewareConfig
        """
        return list(self._configurations.values())
    
    def get_config(self, name: str) -> Optional[MiddlewareConfig]:
        """Get middleware configuration.
        
        Args:
            name: Middleware name
            
        Returns:
            MiddlewareConfig or None
        """
        return self._configurations.get(name)
    
    def update_config(self, name: str, **updates) -> bool:
        """Update middleware configuration.
        
        Args:
            name: Middleware name
            **updates: Configuration updates
            
        Returns:
            True if updated
        """
        with self._lock:
            config = self._configurations.get(name)
            if not config:
                return False
            
            if 'order' in updates:
                config.order = updates.pop('order')
            if 'enabled' in updates:
                config.enabled = updates.pop('enabled')
            if 'nodes' in updates:
                config.nodes = updates.pop('nodes')
            
            for key, value in updates.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            
            return True
    
    def clear(self) -> None:
        """Clear all middleware configurations."""
        with self._lock:
            self._configurations.clear()
            self._chains.clear()
            self._node_chains.clear()


_global_manager: Optional[MiddlewareManager] = None


def get_middleware_manager() -> MiddlewareManager:
    """Get or create the global middleware manager singleton.
    
    Returns:
        Global MiddlewareManager
    """
    global _global_manager
    if _global_manager is None:
        _global_manager = MiddlewareManager()
    return _global_manager


class LangGraphMiddlewareIntegration:
    """Integration helper for applying middleware to LangGraph.
    
    This class provides utilities to wrap LangGraph nodes with middleware.
    """
    
    def __init__(self, manager: Optional[MiddlewareManager] = None):
        self.manager = manager or get_middleware_manager()
    
    def wrap_node(
        self,
        node_func: Callable,
        node_name: str,
        graph_name: str = "graph"
    ) -> Callable:
        """Wrap a LangGraph node function with middleware.
        
        Args:
            node_func: Original node function
            node_name: Node name
            graph_name: Graph name for context
            
        Returns:
            Wrapped function with middleware
        """
        def wrapped_node(state: Any, **kwargs) -> Any:
            context = MiddlewareContext(
                graph_name=graph_name,
                node_name=node_name,
                thread_id=kwargs.get('config', {}).get('configurable', {}).get('thread_id')
            )
            
            chain = self.manager.get_node_chain(node_name)
            if chain:
                import asyncio
                if asyncio.iscoroutinefunction(node_func):
                    async def async_handler():
                        return await node_func(state, **kwargs)
                    return asyncio.run(chain.execute(context, state, async_handler))
                else:
                    return chain.execute_sync(context, state, lambda: node_func(state, **kwargs))
            
            return node_func(state, **kwargs)
        
        return wrapped_node
    
    def apply_to_graph(
        self,
        graph_builder,
        graph_name: str = "graph"
    ) -> None:
        """Apply middleware to a StateGraph.
        
        Args:
            graph_builder: StateGraph builder
            graph_name: Graph name
        """
        pass


def create_middleware_from_config(config: dict[str, Any]) -> Middleware:
    """Create a middleware from configuration dict.
    
    Args:
        config: Middleware configuration
        
    Returns:
        Middleware instance
    """
    middleware_type = config.get('type', 'logging')
    
    if middleware_type == 'logging':
        from .core import LoggingMiddleware
        return LoggingMiddleware(
            name=config.get('name'),
            log_level=config.get('log_level', 20),
            log_state=config.get('log_state', False),
            log_timing=config.get('log_timing', True)
        )
    elif middleware_type == 'exception':
        from .core import ExceptionHandlerMiddleware
        return ExceptionHandlerMiddleware(
            name=config.get('name'),
            log_errors=config.get('log_errors', True),
            reraise=config.get('reraise', False),
            fallback_value=config.get('fallback_value')
        )
    elif middleware_type == 'rate_limit':
        from .interceptor import RateLimitMiddleware
        return RateLimitMiddleware(
            name=config.get('name'),
            max_calls=config.get('max_calls', 100),
            window_seconds=config.get('window_seconds', 60)
        )
    elif middleware_type == 'cache':
        from .interceptor import CachingMiddleware
        return CachingMiddleware(
            name=config.get('name'),
            cache_ttl_seconds=config.get('cache_ttl_seconds', 300),
            max_cache_size=config.get('max_cache_size', 1000)
        )
    else:
        raise ValueError(f"Unknown middleware type: {middleware_type}")