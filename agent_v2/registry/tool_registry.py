"""Tool Registry Core Implementation

Provides the core registry for managing tool registration, validation, and lifecycle.
Following the architecture: Tool Registry + Capability Resolver for dynamic binding

Features:
- Thread-safe tool registration/unregistration
- Dynamic tool enable/disable
- Tool usage statistics tracking
- Permission-based access control
- Tool dependency management

This is a key component for implementing the "按场景动态绑定" (dynamic binding by scenario) 
pattern from the architecture document.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Type
import threading
import inspect

from langchain_core.tools import BaseTool

from .schema_builder import SchemaBuilder
from .enums import PermissionLevel
from .factory import _create_tool_from_callable


@dataclass
class ToolMetadata:
    """Metadata for registered tools"""
    name: str
    description: str
    version: str = "1.0.0"
    author: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    permission: PermissionLevel = PermissionLevel.PUBLIC
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    deprecated: bool = False
    deprecation_message: Optional[str] = None


@dataclass
class RegisteredTool:
    """Registered tool with metadata"""
    metadata: ToolMetadata
    tool: BaseTool
    handler: Optional[Callable] = None
    schema: Optional[dict] = None
    enabled: bool = True
    call_count: int = 0
    error_count: int = 0
    last_called: Optional[datetime] = None


class ToolRegistry:
    """Central registry for managing tool registration and lifecycle
    
    This is the core component for implementing dynamic tool binding.
    Following the architecture principle: Tool Registry + Capability Resolver
    
    Usage:
        registry = ToolRegistry()
        registry.register(my_tool, name="search", tags=["research", "web"])
        
        # Get tools by capability
        research_tools = registry.get_tools_by_tags(["research"])
        
        # Dynamic binding
        capability_tools = registry.get_tools(capabilities=["search", "retrieve"])
    """
    
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}
        self._aliases: dict[str, str] = {}
        self._lock = threading.RLock()
    
    def register(
        self,
        tool: BaseTool | Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: str = "1.0.0",
        author: Optional[str] = None,
        tags: Optional[list[str]] = None,
        permission: PermissionLevel = PermissionLevel.PUBLIC,
        enabled: bool = True,
        auto_schema: bool = True,
        **metadata_kwargs
    ) -> str:
        """Register a tool with the registry
        
        Args:
            tool: BaseTool instance or callable function
            name: Custom tool name (uses tool name if None)
            description: Tool description
            version: Tool version
            author: Tool author
            tags: Tool tags for categorization
            permission: Permission level
            enabled: Whether tool is enabled
            auto_schema: Auto-generate schema from tool
            
        Returns:
            Registered tool name
        """
        with self._lock:
            if isinstance(tool, BaseTool):
                tool_instance = tool
                tool_name = name or tool.name
                tool_description = description or getattr(tool, 'description', '')
            else:
                tool_instance = _create_tool_from_callable(tool)
                tool_name = name or getattr(tool, '__name__', 'unnamed')
                tool_description = description or inspect.getdoc(tool) or ''
            
            metadata = ToolMetadata(
                name=tool_name,
                description=tool_description,
                version=version,
                author=author,
                tags=tags or [],
                permission=permission,
                **metadata_kwargs
            )
            
            registered_tool = RegisteredTool(
                metadata=metadata,
                tool=tool_instance,
                enabled=enabled,
            )
            
            if auto_schema:
                registered_tool.schema = SchemaBuilder.build_schema(tool_instance)
            
            self._tools[tool_name] = registered_tool
            
            return tool_name
    
    def unregister(self, name: str) -> bool:
        """Unregister a tool
        
        Args:
            name: Tool name
            
        Returns:
            True if tool was unregistered
        """
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                return True
            return False
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get tool by name
        
        Args:
            name: Tool name
            
        Returns:
            BaseTool instance or None
        """
        with self._lock:
            registered = self._tools.get(name)
            return registered.tool if registered else None
    
    def get_tools(
        self,
        names: Optional[list[str]] = None,
        capabilities: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        enabled_only: bool = True
    ) -> list[BaseTool]:
        """Get tools with filtering
        
        Args:
            names: Specific tool names
            capabilities: Filter by capabilities (uses tags)
            tags: Filter by tags
            enabled_only: Only return enabled tools
            
        Returns:
            List of BaseTool instances
        """
        with self._lock:
            tools = []
            
            if names:
                for name in names:
                    if name in self._tools:
                        rt = self._tools[name]
                        if not enabled_only or rt.enabled:
                            tools.append(rt.tool)
            elif capabilities or tags:
                filter_tags = set(capabilities or []) | set(tags or [])
                for rt in self._tools.values():
                    if enabled_only and not rt.enabled:
                        continue
                    if not filter_tags or any(t in rt.metadata.tags for t in filter_tags):
                        tools.append(rt.tool)
            else:
                for rt in self._tools.values():
                    if not enabled_only or rt.enabled:
                        tools.append(rt.tool)
            
            return tools
    
    def get_tools_by_tags(self, tags: list[str]) -> list[BaseTool]:
        """Get tools matching any of the given tags
        
        Args:
            tags: List of tags
            
        Returns:
            List of matching tools
        """
        return self.get_tools(tags=tags)
    
    def get_capability_tools(self, capability: str) -> list[BaseTool]:
        """Get tools for a specific capability
        
        Args:
            capability: Capability name
            
        Returns:
            List of tools for this capability
        """
        return self.get_tools(tags=[capability])
    
    def enable(self, name: str) -> bool:
        """Enable a tool
        
        Args:
            name: Tool name
            
        Returns:
            True if tool was enabled
        """
        with self._lock:
            if name in self._tools:
                self._tools[name].enabled = True
                return True
            return False
    
    def disable(self, name: str) -> bool:
        """Disable a tool
        
        Args:
            name: Tool name
            
        Returns:
            True if tool was disabled
        """
        with self._lock:
            if name in self._tools:
                self._tools[name].enabled = False
                return True
            return False
    
    def is_enabled(self, name: str) -> bool:
        """Check if tool is enabled
        
        Args:
            name: Tool name
            
        Returns:
            True if enabled
        """
        with self._lock:
            if name in self._tools:
                return self._tools[name].enabled
            return False
    
    def record_call(self, name: str, error: bool = False):
        """Record tool call
        
        Args:
            name: Tool name
            error: Whether call resulted in error
        """
        with self._lock:
            if name in self._tools:
                rt = self._tools[name]
                rt.call_count += 1
                if error:
                    rt.error_count += 1
                rt.last_called = datetime.now()
    
    def get_stats(self, name: str) -> Optional[dict]:
        """Get tool usage statistics
        
        Args:
            name: Tool name
            
        Returns:
            Stats dict or None
        """
        with self._lock:
            if name not in self._tools:
                return None
            
            rt = self._tools[name]
            return {
                'name': name,
                'call_count': rt.call_count,
                'error_count': rt.error_count,
                'success_rate': (rt.call_count - rt.error_count) / rt.call_count if rt.call_count > 0 else 0,
                'last_called': rt.last_called.isoformat() if rt.last_called else None,
                'enabled': rt.enabled,
            }
    
    def list_tools(self, enabled_only: bool = False) -> list[str]:
        """List all registered tool names
        
        Args:
            enabled_only: Only list enabled tools
            
        Returns:
            List of tool names
        """
        with self._lock:
            if enabled_only:
                return [name for name, rt in self._tools.items() if rt.enabled]
            return list(self._tools.keys())
    
    def get_all_metadata(self) -> list[dict]:
        """Get metadata for all tools
        
        Returns:
            List of metadata dicts
        """
        with self._lock:
            return [
                {
                    'name': rt.metadata.name,
                    'description': rt.metadata.description,
                    'version': rt.metadata.version,
                    'author': rt.metadata.author,
                    'tags': rt.metadata.tags,
                    'permission': rt.metadata.permission.value,
                    'enabled': rt.enabled,
                    'deprecated': rt.metadata.deprecated,
                }
                for rt in self._tools.values()
            ]


_global_registry = ToolRegistry()


def get_global_registry() -> ToolRegistry:
    """Get global tool registry instance
    
    Returns:
        Global ToolRegistry instance
    """
    return _global_registry


def register_tool(
    tool: BaseTool | Callable,
    name: Optional[str] = None,
    **kwargs
) -> str:
    """Convenience function to register tool to global registry
    
    Args:
        tool: Tool or callable
        name: Optional name
        
    Returns:
        Tool name
    """
    return _global_registry.register(tool, name=name, **kwargs)


def get_tool(name: str) -> Optional[BaseTool]:
    """Convenience function to get tool from global registry"""
    return _global_registry.get_tool(name)


def get_tools_by_capability(capability: str) -> list[BaseTool]:
    """Convenience function to get tools by capability"""
    return _global_registry.get_capability_tools(capability)