"""Registry Module

Implements the registry layer following the architecture document:
- Tool Registry: Tool registration and lifecycle management
- Capability Registry: Capability to tool mapping
- Tool Factory: Dynamic tool creation

Architecture pattern:
Tool Registry + Capability Resolver = Dynamic Tool Binding

This enables the "按场景动态绑定" (dynamic binding by scenario) pattern:
- User request
- Intent Detection
- Select capability
- Dynamic inject tools
- Execute LLM
"""

from .tool_registry import (
    ToolRegistry,
    ToolMetadata,
    RegisteredTool,
    get_global_registry,
    register_tool,
    get_tool,
    get_tools_by_capability,
)

from .capability_registry import (
    CapabilityRegistry,
    CapabilityConfig,
    get_global_capability_registry,
    register_capability,
    get_capability_tools,
)

from .schema_builder import SchemaBuilder

from .factory import (
    ToolFactory,
    ToolSpec,
    SkeletonToolSpec,
)

from .enums import (
    PermissionLevel,
    ToolStatus,
    ToolCapability,
)

__all__ = [
    # Tool Registry
    "ToolRegistry",
    "ToolMetadata",
    "RegisteredTool",
    "get_global_registry",
    "register_tool",
    "get_tool",
    "get_tools_by_capability",
    # Capability Registry
    "CapabilityRegistry",
    "CapabilityConfig",
    "get_global_capability_registry",
    "register_capability",
    "get_capability_tools",
    # Schema Builder
    "SchemaBuilder",
    # Factory
    "ToolFactory",
    "ToolSpec",
    "SkeletonToolSpec",
    # Enums
    "PermissionLevel",
    "ToolStatus",
    "ToolCapability",
]