"""Tool Factory Module

Creates tools from specifications, schemas, and various sources.

Three creation patterns from architecture doc:
1. Skeleton - AI defines template, human implements logic
2. With Handler - Spec + handler function
3. Dynamic - Spec with code string that executes directly

Following the architecture: Dynamic tool binding + Tool Registry
"""

from typing import Any, Callable, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
import inspect

from langchain_core.tools import tool, BaseTool

if TYPE_CHECKING:
    from .tool_registry import ToolRegistry

from .schema_builder import SchemaBuilder


@dataclass
class ToolSpec:
    """Tool specification for creation"""
    name: str
    description: str
    parameters: Optional[dict[str, Any]] = None
    returns: Optional[dict[str, Any]] = None
    examples: Optional[list[dict[str, Any]]] = None
    tags: Optional[list[str]] = None
    permission: str = "public"
    version: str = "1.0.0"
    author: Optional[str] = None
    code: Optional[str] = None


@dataclass
class SkeletonToolSpec(ToolSpec):
    """Tool specification for skeleton tools
    
    AI generates the template, human implements the actual logic.
    """
    implementation_required: bool = True
    hints: Optional[str] = None


class ToolFactory:
    """Factory for creating and configuring tools
    
    Features:
    - Create skeleton tools (AI template, human implementation)
    - Create tools from specifications with handlers
    - Create tools from callable functions
    - Tool composition
    
    Following the architecture pattern for dynamic tool binding.
    """
    
    CREATE_MODE_SKELETON = "skeleton"
    CREATE_MODE_HANDLER = "handler"
    CREATE_MODE_DYNAMIC = "dynamic"
    
    def __init__(self, registry: Optional["ToolRegistry"] = None):
        """Initialize factory
        
        Args:
            registry: Optional tool registry
        """
        self.registry = registry
        self._schema_builder = SchemaBuilder()
        self._handler_registry: dict[str, Callable] = {}
    
    def register_handler(self, name: str, handler: Callable) -> None:
        """Register a handler function
        
        Args:
            name: Handler name
            handler: Callable function
        """
        self._handler_registry[name] = handler
    
    def create_skeleton(
        self,
        spec: SkeletonToolSpec
    ) -> tuple[BaseTool, dict]:
        """Create skeleton tool from spec
        
        Args:
            spec: Skeleton tool specification
            
        Returns:
            Tuple of (skeleton_tool, implementation_template)
        """
        template = {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters or {},
            "implementation_template": self._generate_implementation_template(spec),
            "hints": spec.hints,
        }
        
        @tool(name=spec.name, description=spec.description)
        def skeleton_tool(**kwargs) -> str:
            return f"Implementation pending: {spec.name}"
        
        return skeleton_tool, template
    
    def create_from_handler(
        self,
        spec: ToolSpec,
        handler: Callable
    ) -> BaseTool:
        """Create tool from specification with handler
        
        Args:
            spec: Tool specification
            handler: Handler function
            
        Returns:
            BaseTool instance
        """
        tool_name = spec.name
        
        @tool(name=tool_name, description=spec.description)
        def generated_tool(**kwargs) -> Any:
            return handler(**kwargs)
        
        if self.registry:
            self.registry.register(
                generated_tool,
                name=tool_name,
                description=spec.description,
                tags=spec.tags,
            )
        
        return generated_tool
    
    def create_from_callable(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None
    ) -> BaseTool:
        """Create tool from callable function
        
        Args:
            func: Callable function
            name: Optional tool name
            description: Optional description
            tags: Optional tags
            
        Returns:
            BaseTool instance
        """
        return _create_tool_from_callable(
            func,
            name=name,
            description=description,
            tags=tags
        )
    
    def create_dynamic(
        self,
        spec: ToolSpec,
        code: str
    ) -> BaseTool:
        """Create dynamic tool from code string
        
        Args:
            spec: Tool specification
            code: Code string to execute
            
        Returns:
            BaseTool instance
        """
        namespace = {}
        
        try:
            exec(code, namespace)
        except Exception as e:
            raise ValueError(f"Failed to execute tool code: {e}")
        
        handler = namespace.get(spec.name)
        if not handler:
            raise ValueError(f"Handler '{spec.name}' not found in code")
        
        return self.create_from_handler(spec, handler)
    
    def _generate_implementation_template(self, spec: SkeletonToolSpec) -> str:
        """Generate implementation template for skeleton tool
        
        Args:
            spec: Skeleton specification
            
        Returns:
            Template code string
        """
        params = spec.parameters or {}
        param_names = list(params.keys())
        param_str = ", ".join(param_names) if param_names else ""
        
        template = f'''
def {spec.name}({param_str}):
    """
    {spec.description}
    
    {"TODO: Implement this function" if spec.implementation_required else "Already implemented"}
    
    Parameters:
{self._format_params_doc(params)}
    
    Returns:
        Result of the operation
    """
    # Your implementation here
    pass
'''
        return template
    
    def _format_params_doc(self, params: dict) -> str:
        """Format parameters for documentation
        
        Args:
            params: Parameters dict
            
        Returns:
            Formatted docstring
        """
        lines = []
        for param_name, param_info in params.items():
            param_type = param_info.get("type", "any")
            param_desc = param_info.get("description", "")
            lines.append(f"        {param_name} ({param_type}): {param_desc}")
        return "\n".join(lines) if lines else "        (no parameters)"


def _create_tool_from_callable(
    func: Callable,
    name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[list[str]] = None
) -> BaseTool:
    """Create tool from callable function
    
    Args:
        func: Callable function
        name: Optional tool name
        description: Optional description
        tags: Optional tags
        
    Returns:
        BaseTool instance
    """
    tool_name = name or getattr(func, '__name__', 'unnamed')
    tool_description = description or inspect.getdoc(func) or f"Tool: {tool_name}"
    
    @tool(name=tool_name, description=tool_description)
    def wrapper(**kwargs) -> Any:
        return func(**kwargs)
    
    return wrapper