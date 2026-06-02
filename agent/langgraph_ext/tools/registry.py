"""Tool Registry Core Implementation

Provides the core registry for managing tool registration, validation, and lifecycle.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Type
import inspect

from langchain_core.tools import BaseTool

from .schema_builder import SchemaBuilder
from .enums import PermissionLevel
from .factory import _create_tool_from_callable


@dataclass
class ToolMetadata:
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
    metadata: ToolMetadata
    tool: BaseTool
    handler: Optional[Callable] = None
    schema: Optional[dict] = None
    enabled: bool = True
    call_count: int = 0
    error_count: int = 0
    last_called: Optional[datetime] = None


class ToolRegistry:
    """Central registry for managing tool registration and lifecycle.
    
    Features:
    - Thread-safe tool registration/unregistration
    - Dynamic tool enable/disable
    - Tool usage statistics tracking
    - Permission-based access control
    - Tool dependency management
    """
    
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}
        self._aliases: dict[str, str] = {}
        self._lock = __import__('threading').Lock()
    
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
        """Register a tool with the registry.
        
        Args:
            tool: BaseTool instance or callable function
            name: Custom tool name (uses tool name if None)
            description: Tool description
            version: Tool version
            author: Tool author
            tags: Tags for categorization
            permission: Permission level
            enabled: Whether tool is enabled
            auto_schema: Whether to automatically generate schema from function signature
            **metadata_kwargs: Additional metadata fields
            
        Returns:
            Tool name as registered
        """
        with self._lock:
            if isinstance(tool, BaseTool):
                tool_name = name or tool.name
            else:
                tool_name = name or getattr(tool, '__name__', 'anonymous')
            
            if tool_name in self._tools:
                raise ValueError(f"Tool '{tool_name}' is already registered. Use update() to modify.")
            
            if description is None and isinstance(tool, BaseTool):
                description = getattr(tool, 'description', '')
            
            metadata = ToolMetadata(
                name=tool_name,
                description=description or '',
                version=version,
                author=author,
                tags=tags or [],
                permission=permission,
                **metadata_kwargs
            )
            
            schema = None
            if isinstance(tool, BaseTool):
                registered_tool = RegisteredTool(
                    metadata=metadata,
                    tool=tool,
                    handler=None
                )
            else:
                base_tool = self._create_base_tool_from_callable(
                    tool, tool_name, description or '', auto_schema
                )
                if auto_schema:
                    schema = SchemaBuilder().build_schema_from_function(tool)
                registered_tool = RegisteredTool(
                    metadata=metadata,
                    tool=base_tool,
                    handler=tool,
                    schema=schema
                )
            
            self._tools[tool_name] = registered_tool
            return tool_name
    
    def _create_base_tool_from_callable(
        self,
        func: Callable,
        name: str,
        description: str,
        auto_schema: bool = True
    ) -> BaseTool:
        """Create a BaseTool from a callable function.

        Args:
            func: The callable function
            name: Tool name
            description: Tool description
            auto_schema: Whether to auto-generate schema from function signature

        Returns:
            BaseTool instance with args_schema
        """
        return _create_tool_from_callable(
            func=func,
            name=name,
            description=description,
            auto_schema=auto_schema,
            schema_builder=SchemaBuilder()
        )
    
    def unregister(self, name: str) -> bool:
        """Unregister a tool.
        
        Args:
            name: Tool name
            
        Returns:
            True if tool was unregistered, False if not found
        """
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                for alias, original in list(self._aliases.items()):
                    if original == name:
                        del self._aliases[alias]
                return True
            return False
    
    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name.
        
        Args:
            name: Tool name or alias
            
        Returns:
            BaseTool instance or None if not found
        """
        resolved_name = self._aliases.get(name, name)
        registered = self._tools.get(resolved_name)
        return registered.tool if registered else None
    
    def get_registered_tool(self, name: str) -> Optional[RegisteredTool]:
        """Get the full RegisteredTool object.
        
        Args:
            name: Tool name
            
        Returns:
            RegisteredTool or None if not found
        """
        resolved_name = self._aliases.get(name, name)
        return self._tools.get(resolved_name)
    
    def list_tools(
        self,
        tags: Optional[list[str]] = None,
        permission: Optional[PermissionLevel] = None,
        include_disabled: bool = False
    ) -> list[RegisteredTool]:
        """List registered tools with optional filtering.
        
        Args:
            tags: Filter by tags
            permission: Filter by permission level
            include_disabled: Include disabled tools
            
        Returns:
            List of RegisteredTool objects
        """
        tools = []
        for tool in self._tools.values():
            if not include_disabled and not tool.enabled:
                continue
            if permission and tool.metadata.permission != permission:
                continue
            if tags and not any(tag in tool.metadata.tags for tag in tags):
                continue
            tools.append(tool)
        return tools
    
    def update(self, name: str, **updates) -> bool:
        """Update tool metadata or settings.
        
        Args:
            name: Tool name
            **updates: Fields to update
            
        Returns:
            True if updated, False if tool not found
        """
        with self._lock:
            tool = self._tools.get(name)
            if not tool:
                return False
            
            if 'description' in updates:
                tool.metadata.description = updates.pop('description')
            if 'version' in updates:
                tool.metadata.version = updates.pop('version')
            if 'tags' in updates:
                tool.metadata.tags = updates.pop('tags')
            if 'permission' in updates:
                tool.metadata.permission = updates.pop('permission')
            if 'enabled' in updates:
                tool.enabled = updates.pop('enabled')
            
            tool.metadata.updated_at = datetime.now()
            
            for key, value in updates.items():
                if hasattr(tool.metadata, key):
                    setattr(tool.metadata, key, value)
            
            return True
    
    def enable(self, name: str) -> bool:
        """Enable a tool.
        
        Args:
            name: Tool name
            
        Returns:
            True if enabled, False if not found
        """
        return self.update(name, enabled=True)
    
    def disable(self, name: str) -> bool:
        """Disable a tool.
        
        Args:
            name: Tool name
            
        Returns:
            True if disabled, False if not found
        """
        return self.update(name, enabled=False)
    
    def add_alias(self, alias: str, tool_name: str) -> bool:
        """Add an alias for a tool.
        
        Args:
            alias: Alias name
            tool_name: Original tool name
            
        Returns:
            True if alias added, False if tool not found
        """
        if tool_name not in self._tools:
            return False
        with self._lock:
            self._aliases[alias] = tool_name
        return True
    
    def record_call(self, name: str, error: bool = False) -> None:
        """Record a tool call for statistics.
        
        Args:
            name: Tool name
            error: Whether the call resulted in an error
        """
        tool = self._tools.get(name)
        if tool:
            tool.call_count += 1
            if error:
                tool.error_count += 1
            tool.last_called = datetime.now()
    
    def get_stats(self, name: str) -> Optional[dict]:
        """Get usage statistics for a tool.
        
        Args:
            name: Tool name
            
        Returns:
            Statistics dict or None if not found
        """
        tool = self._tools.get(name)
        if not tool:
            return None
        return {
            'name': name,
            'call_count': tool.call_count,
            'error_count': tool.error_count,
            'last_called': tool.last_called.isoformat() if tool.last_called else None,
            'error_rate': tool.error_count / tool.call_count if tool.call_count > 0 else 0,
            'enabled': tool.enabled
        }
    
    def check_permission(
        self,
        name: str,
        required_level: PermissionLevel = PermissionLevel.PUBLIC
    ) -> bool:
        """Check if a tool meets the required permission level.
        
        Args:
            name: Tool name
            required_level: Required permission level
            
        Returns:
            True if permission check passes
        """
        tool = self._tools.get(name)
        if not tool:
            return False
        
        level_order = {
            PermissionLevel.PUBLIC: 0,
            PermissionLevel.PROTECTED: 1,
            PermissionLevel.PRIVATE: 2
        }
        
        tool_level = level_order.get(tool.metadata.permission, 0)
        required = level_order.get(required_level, 0)
        
        return tool_level <= required
    
    def validate_tool_signature(self, name: str, **kwargs) -> tuple[bool, Optional[str]]:
        """Validate that tool can accept the given arguments.
        
        Args:
            name: Tool name
            **kwargs: Arguments to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        tool = self._tools.get(name)
        if not tool:
            return False, f"Tool '{name}' not found"
        
        if not tool.enabled:
            return False, f"Tool '{name}' is disabled"
        
        if isinstance(tool.tool, BaseTool):
            try:
                sig = inspect.signature(tool.tool.run)
                sig.bind(**kwargs)
                return True, None
            except TypeError as e:
                return False, f"Invalid arguments: {e}"
        
        return True, None
    
    def to_langchain_tools(self) -> list[BaseTool]:
        """Export all registered tools as LangChain BaseTool list.
        
        Returns:
            List of BaseTool instances
        """
        return [
            tool.tool for tool in self._tools.values()
            if tool.enabled and not tool.metadata.deprecated
        ]


_global_registry: Optional[ToolRegistry] = None


def get_global_registry() -> ToolRegistry:
    """Get or create the global tool registry singleton.
    
    Returns:
        Global ToolRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def register_tool(
    tool: BaseTool | Callable,
    name: Optional[str] = None,
    **kwargs
) -> str:
    """Convenience function to register a tool with the global registry.
    
    Args:
        tool: Tool to register
        name: Optional tool name
        **kwargs: Additional registration options
        
    Returns:
        Registered tool name
    """
    return get_global_registry().register(tool, name, **kwargs)


def get_tool(name: str) -> Optional[BaseTool]:
    """Convenience function to get a tool from the global registry.
    
    Args:
        name: Tool name
        
    Returns:
        BaseTool or None
    """
    return get_global_registry().get(name)


def list_tools(**kwargs) -> list[RegisteredTool]:
    """Convenience function to list tools from the global registry.
    
    Args:
        **kwargs: Filter options
        
    Returns:
        List of RegisteredTool
    """
    return get_global_registry().list_tools(**kwargs)