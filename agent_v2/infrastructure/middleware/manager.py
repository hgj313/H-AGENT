"""Middleware Manager Module

Manages middleware configuration, lifecycle, and integration with LangGraph.
Following the architecture: Middleware = interception layer

Features:
- Middleware registration and configuration
- Lifecycle management
- Node-specific middleware
- Hot-swapping
- Integration with LangGraph
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
    """Middleware integration modes"""
    NODE_WRAPPER = "node_wrapper"
    GRAPH_INJECTION = "graph_injection"
    CHECKPOINT = "checkpoint"


@dataclass
class MiddlewareConfig:
    """Configuration for a middleware"""
    name: str
    middleware_class: type[Middleware]
    order: MiddlewareOrder = MiddlewareOrder.NORMAL
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    nodes: Optional[list[str]] = None


class MiddlewareManager:
    """Manages middleware lifecycle and integration
    
    Following the architecture: Middleware management
    
    Usage:
        manager = MiddlewareManager()
        
        # Register middleware
        manager.register(
            "logging",
            LoggingMiddleware(log_level=logging.DEBUG),
            nodes=["agent_node", "tool_node"]
        )
        
        # Execute with middleware
        result = manager.execute_node(
            "agent_node",
            context,
            state,
            handler
        )
    """
    
    def __init__(self):
        self._configurations: dict[str, MiddlewareConfig] = {}
        self._chains: dict[str, MiddlewareChain] = {}
        self._node_chains: dict[str, MiddlewareChain] = {}
        self._lock = threading.RLock()
    
    def configure(self, config: MiddlewareConfig) -> None:
        """Configure a middleware
        
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
        """Register a middleware instance
        
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
        """Unregister a middleware
        
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
        """Get middleware chain by name
        
        Args:
            name: Chain name
            
        Returns:
            MiddlewareChain or None
        """
        return self._chains.get(name)
    
    def get_node_chain(self, node_name: str) -> Optional[MiddlewareChain]:
        """Get middleware chain for a specific node
        
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
        """Execute a node with its middleware chain
        
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
    
    async def execute_node_async(
        self,
        node_name: str,
        context: MiddlewareContext,
        state: Any,
        handler: Callable
    ) -> Any:
        """Execute a node asynchronously with its middleware chain
        
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
            return await chain.execute(context, state, handler)
        return await handler()
    
    def enable(self, name: str) -> bool:
        """Enable a middleware
        
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
        """Disable a middleware
        
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
        """List all configured middlewares
        
        Returns:
            List of MiddlewareConfig
        """
        with self._lock:
            return list(self._configurations.values())
    
    def get_enabled_middlewares(self) -> list[str]:
        """Get list of enabled middleware names
        
        Returns:
            List of middleware names
        """
        with self._lock:
            return [
                name for name, config in self._configurations.items()
                if config.enabled
            ]
    
    def clear_node_chain(self, node_name: str) -> bool:
        """Clear middleware chain for a node
        
        Args:
            node_name: Node name
            
        Returns:
            True if cleared
        """
        with self._lock:
            if node_name in self._node_chains:
                self._node_chains[node_name].clear()
                return True
            return False
    
    def create_context(
        self,
        graph_name: str,
        node_name: Optional[str] = None,
        thread_id: Optional[str] = None,
        run_id: Optional[str] = None,
        **metadata
    ) -> MiddlewareContext:
        """Create a middleware context
        
        Args:
            graph_name: Graph name
            node_name: Optional node name
            thread_id: Optional thread ID
            run_id: Optional run ID
            **metadata: Additional metadata
            
        Returns:
            MiddlewareContext
        """
        return MiddlewareContext(
            graph_name=graph_name,
            node_name=node_name,
            thread_id=thread_id,
            run_id=run_id,
            metadata=metadata
        )


def create_middleware_manager() -> MiddlewareManager:
    """Factory function to create middleware manager
    
    Returns:
        MiddlewareManager instance
    """
    return MiddlewareManager()