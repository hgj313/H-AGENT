"""Tool Factory Module

Creates tools from specifications, schemas, and various sources.

Three creation patterns:
1. Skeleton - AI defines template, human implements logic
2. With Handler - Spec + handler function
3. Dynamic - Spec with code string that executes directly
"""

from typing import Any, Callable, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
import inspect

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from .registry import ToolRegistry
else:
    pass

from .schema_builder import SchemaBuilder
from .enums import PermissionLevel


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Optional[dict[str, Any]] = None
    returns: Optional[dict[str, Any]] = None
    examples: Optional[list[dict[str, Any]]] = None
    tags: Optional[list[str]] = None
    permission: PermissionLevel = PermissionLevel.PUBLIC
    version: str = "1.0.0"
    author: Optional[str] = None
    code: Optional[str] = None
    template_fields: Optional[list[str]] = None


@dataclass
class SkeletonToolSpec(ToolSpec):
    """Tool specification for skeleton tools.

    AI generates the template, human implements the actual logic.
    """
    implementation_required: bool = True
    hints: Optional[str] = None


class ToolFactory:
    """Factory for creating and configuring tools.

    Features:
    - Create skeleton tools (AI template, human implementation)
    - Create tools from specifications with handlers
    - Create tools from callable functions
    - Create dynamic tools from code strings
    - Tool composition
    """

    CREATE_MODE_SKELETON = "skeleton"
    CREATE_MODE_HANDLER = "handler"
    CREATE_MODE_DYNAMIC = "dynamic"

    def __init__(self, registry: Optional["ToolRegistry"] = None):
        self.registry = registry
        self._schema_builder = SchemaBuilder()
        self._handler_registry: dict[str, Callable] = {}

    def register_handler(self, name: str, handler: Callable) -> None:
        """Register a handler function for later use.

        Args:
            name: Handler name
            handler: Callable function
        """
        self._handler_registry[name] = handler

    def create_skeleton(
        self,
        spec: ToolSpec | SkeletonToolSpec | dict,
        hints: Optional[str] = None
    ) -> BaseTool:
        """Create a skeleton tool (template without implementation).

        AI generates the template structure, human implements the actual logic.
        The created tool will raise NotImplementedError when invoked.

        Args:
            spec: Tool specification
            hints: Optional implementation hints for developers

        Returns:
            BaseTool instance with skeleton implementation

        Use case:
            1. AI generates skeleton spec with template_fields
            2. Human reviews and implements the logic
            3. Tool becomes fully functional
        """
        if isinstance(spec, dict):
            spec = SkeletonToolSpec(**spec) if hints or spec.get('implementation_required') else ToolSpec(**spec)

        if not isinstance(spec, SkeletonToolSpec):
            spec = SkeletonToolSpec(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
                returns=spec.returns,
                examples=spec.examples,
                tags=spec.tags,
                permission=spec.permission,
                version=spec.version,
                author=spec.author,
                hints=hints,
            )

        return _create_skeleton_tool(spec)

    def create_from_spec(
        self,
        spec: ToolSpec | dict,
        handler: Optional[Callable] = None
    ) -> BaseTool:
        """Create a tool from a specification.

        Automatically detects creation mode based on spec content:
        - Has 'code' field -> Dynamic tool
        - Has 'handler_name' field -> Uses registered handler
        - Otherwise -> Requires explicit handler argument

        Args:
            spec: Tool specification
            handler: Optional handler function to execute when tool is invoked

        Returns:
            BaseTool instance

        Example:
            # With explicit handler
            tool = factory.create_from_spec(spec, handler=my_func)

            # With code (dynamic)
            spec_with_code = {**spec, "code": "result = a + b"}
            tool = factory.create_from_spec(spec_with_code)
        """
        if isinstance(spec, dict):
            spec = ToolSpec(**spec)

        if spec.code:
            from .dynamic_tool import DynamicToolFactory, DynamicToolSpec
            dyn_spec = DynamicToolSpec(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
                code=spec.code,
            )
            return DynamicToolFactory().create_from_spec(dyn_spec)

        return _create_tool_from_spec(spec, handler)

    def create_from_callable(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        auto_schema: bool = True
    ) -> BaseTool:
        """Create a tool from a callable function.

        Args:
            func: Function to wrap as tool
            name: Tool name (uses function name if None)
            description: Tool description (uses function docstring if None)
            auto_schema: Whether to auto-generate schema from function signature

        Returns:
            BaseTool instance with complete implementation
        """
        tool_name = name or getattr(func, '__name__', 'anonymous')
        tool_desc = description or getattr(func, '__doc__', '') or f"Tool: {tool_name}"

        return _create_tool_from_callable(func, tool_name, tool_desc, auto_schema, self._schema_builder)

    def create_wrapper(
        self,
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **metadata
    ) -> BaseTool:
        """Wrap a function as a tool.

        Args:
            func: Function to wrap
            name: Tool name
            description: Tool description
            **metadata: Additional metadata

        Returns:
            BaseTool instance
        """
        tool_name = name or getattr(func, '__name__', 'wrapper_tool')
        tool_desc = description or getattr(func, '__doc__', f'Wrapper for {tool_name}')

        return _create_wrapper_tool(func, tool_name, tool_desc, **metadata)

    def create_composite(
        self,
        tools: list[BaseTool],
        name: str,
        description: str,
        selector: Optional[Callable] = None
    ) -> BaseTool:
        """Create a composite tool that combines multiple tools.

        Args:
            tools: List of tools to compose
            name: Composite tool name
            description: Composite tool description
            selector: Optional function to select which tool to use based on input

        Returns:
            Composite BaseTool
        """
        return _create_composite_tool(tools, name, description, selector)

    def create(
        self,
        spec: ToolSpec | dict,
        mode: str = CREATE_MODE_DYNAMIC,
        handler: Optional[Callable] = None,
        **kwargs
    ) -> BaseTool:
        """Unified creation method with mode switching.

        Args:
            spec: Tool specification
            mode: Creation mode - 'skeleton', 'handler', or 'dynamic'
            handler: Handler function (for 'handler' mode)
            **kwargs: Additional arguments passed to specific creation methods

        Returns:
            BaseTool instance

        Mode selection:
            - 'skeleton': Creates template tool (AI design, human implements)
            - 'handler': Creates tool with handler function
            - 'dynamic': Creates tool with code execution (default)

        Example:
            factory.create(spec, mode='skeleton')
            factory.create(spec, mode='handler', handler=my_func)
            factory.create({**spec, 'code': '...'}, mode='dynamic')
        """
        if mode == self.CREATE_MODE_SKELETON:
            return self.create_skeleton(spec, **kwargs)

        if mode == self.CREATE_MODE_HANDLER:
            return self.create_from_spec(spec, handler)

        if mode == self.CREATE_MODE_DYNAMIC:
            if isinstance(spec, dict) and 'code' in spec:
                return self.create_from_spec(spec)
            return self.create_from_spec(spec, handler)

        raise ValueError(f"Unknown mode: {mode}. Use 'skeleton', 'handler', or 'dynamic'")

    def detect_mode(self, spec: dict | ToolSpec) -> str:
        """Detect the appropriate creation mode from spec.

        Args:
            spec: Tool specification

        Returns:
            Suggested creation mode
        """
        if isinstance(spec, ToolSpec):
            spec_dict = spec.__dict__ if hasattr(spec, '__dict__') else {}
        else:
            spec_dict = spec

        if spec_dict.get('code'):
            return self.CREATE_MODE_DYNAMIC

        if spec_dict.get('template_fields') or spec_dict.get('implementation_required'):
            return self.CREATE_MODE_SKELETON

        if spec_dict.get('handler_name') in self._handler_registry:
            return self.CREATE_MODE_HANDLER

        if spec_dict.get('handler'):
            return self.CREATE_MODE_HANDLER

        return self.CREATE_MODE_DYNAMIC

    def register_and_wrap(
        self,
        func: Callable,
        name: Optional[str] = None,
        **kwargs
    ) -> str:
        """Register a function as a tool and return its name.

        Args:
            func: Function to register
            name: Optional tool name
            **kwargs: Additional registration options

        Returns:
            Registered tool name
        """
        if self.registry is None:
            raise ValueError("No registry configured. Use create_wrapper() instead.")

        return self.registry.register(func, name, **kwargs)


def _create_skeleton_tool(spec: SkeletonToolSpec) -> BaseTool:
    """Create a skeleton tool without implementation.

    Args:
        spec: SkeletonToolSpec with tool structure

    Returns:
        BaseTool instance that raises NotImplementedError on invoke
    """
    tool_name = spec.name
    tool_desc = spec.description
    hints = spec.hints
    params_schema = spec.parameters or {}

    from pydantic import BaseModel, Field, create_model as pydantic_create_model

    args_schema_class = BaseModel
    if params_schema:
        field_definitions = {}
        for param_name, param_info in params_schema.items():
            ptype = param_info.get('type', 'string')
            default = param_info.get('default')
            description = param_info.get('description', '')
            required = param_info.get('required', True)

            type_map = {
                'string': str,
                'integer': int,
                'number': float,
                'boolean': bool,
                'array': list,
                'object': dict
            }

            field_type = type_map.get(ptype, str)
            if required and default is None:
                field_definitions[param_name] = (field_type, ...)
            else:
                field_definitions[param_name] = (field_type, Field(default=default, description=description))

        args_schema_class = pydantic_create_model('SkeletonArgs', **field_definitions)

    class SkeletonTool(BaseTool):
        name: str = tool_name
        description: str = tool_desc
        args_schema: type[BaseModel] = args_schema_class

        def _run(self, *args, **kwargs) -> Any:
            raise NotImplementedError(
                f"Tool '{tool_name}' is a skeleton. Implementation required.\n"
                f"{f'Hints: {hints}' if hints else ''}\n"
                f"Template fields: {spec.template_fields or list(params_schema.keys())}\n"
                f"Please implement the logic and create a complete tool."
            )

        async def _arun(self, *args, **kwargs) -> Any:
            return self._run(*args, **kwargs)

    return SkeletonTool(name=tool_name, description=tool_desc)


def _create_tool_from_spec(
    spec: ToolSpec,
    handler: Optional[Callable] = None
) -> BaseTool:
    """Create a tool from a specification.

    Args:
        spec: Tool specification
        handler: Optional handler function to execute

    Returns:
        BaseTool instance
    """
    tool_name = spec.name
    tool_desc = spec.description
    params_schema = spec.parameters or {}

    from pydantic import BaseModel as PydanticBaseModel, Field, create_model as pydantic_create_model

    args_schema_class = PydanticBaseModel
    if params_schema:
        field_definitions = {}
        for param_name, param_info in params_schema.items():
            ptype = param_info.get('type', 'string')
            default = param_info.get('default')
            description = param_info.get('description', '')

            type_map = {
                'string': str,
                'integer': int,
                'number': float,
                'boolean': bool,
                'array': list,
                'object': dict
            }

            field_type = type_map.get(ptype, str)
            field_definitions[param_name] = (field_type, Field(default=default, description=description))

        args_schema_class = pydantic_create_model('ToolArgs', **field_definitions)

    class SpecTool(BaseTool):
        name: str = tool_name
        description: str = tool_desc
        args_schema: type[PydanticBaseModel] = args_schema_class

        def _run(self, *args, **kwargs) -> Any:
            if handler is None:
                raise NotImplementedError(
                    f"Tool '{tool_name}' has no handler. "
                    f"Please provide a handler or use create_skeleton() for templates."
                )
            sig = inspect.signature(handler)
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return handler(*bound.args, **bound.kwargs)
            except TypeError as e:
                raise ValueError(f"Invalid arguments: {e}")

        async def _arun(self, *args, **kwargs) -> Any:
            if handler is None:
                raise NotImplementedError(
                    f"Tool '{tool_name}' has no handler. "
                    f"Please provide a handler or use create_skeleton() for templates."
                )
            if inspect.iscoroutinefunction(handler):
                sig = inspect.signature(handler)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return await handler(*bound.args, **bound.kwargs)
            return self._run(*args, **kwargs)

    return SpecTool(name=tool_name, description=tool_desc)


def _create_tool_from_callable(
    func: Callable,
    name: str,
    description: str,
    auto_schema: bool,
    schema_builder: SchemaBuilder
) -> BaseTool:
    """Create a BaseTool from a callable function.

    Args:
        func: The callable function
        name: Tool name
        description: Tool description
        auto_schema: Whether to auto-generate schema from function signature
        schema_builder: SchemaBuilder instance

    Returns:
        BaseTool instance with args_schema
    """
    from pydantic import BaseModel as PydanticBaseModel, Field, create_model

    func_name = name
    func_desc = description or getattr(func, '__doc__', '') or f"Tool: {name}"

    args_schema_class = PydanticBaseModel

    if auto_schema:
        generated_schema = schema_builder.build_schema_from_function(func)
        properties = generated_schema.get('properties', {})
        field_definitions = {}

        for param_name, param_info in properties.items():
            ptype = param_info.get('type', 'string')
            default = param_info.get('default', ...)
            desc = param_info.get('description', '')

            type_map = {
                'string': str,
                'integer': int,
                'number': float,
                'boolean': bool,
                'array': list,
                'object': dict
            }

            field_type = type_map.get(ptype, str)

            if desc:
                field_definitions[param_name] = (field_type, Field(default=default, description=desc))
            else:
                field_definitions[param_name] = (field_type, default)

        if field_definitions:
            args_schema_class = create_model('ToolArgs', **field_definitions)

    class DynamicTool(BaseTool):
        name: str = func_name
        description: str = func_desc
        args_schema: type[PydanticBaseModel] = args_schema_class

        def _run(self, *args, **kwargs) -> Any:
            sig = inspect.signature(func)
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return func(*bound.args, **bound.kwargs)
            except TypeError as e:
                raise ValueError(f"Invalid arguments: {e}")

        async def _arun(self, *args, **kwargs) -> Any:
            if inspect.iscoroutinefunction(func):
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return await func(*bound.args, **bound.kwargs)
            return self._run(*args, **kwargs)

    return DynamicTool(name=func_name, description=func_desc)


def _create_wrapper_tool(
    func: Callable,
    name: str,
    description: str,
    **metadata
) -> BaseTool:
    """Create a wrapper tool from a function.

    Args:
        func: Function to wrap
        name: Tool name
        description: Tool description
        **metadata: Additional metadata

    Returns:
        BaseTool instance
    """

    class WrapperTool(BaseTool):
        name: str = name
        description: str = description

        def _run(self, *args, **kwargs) -> Any:
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            return func(*bound.args, **bound.kwargs)

        async def _arun(self, *args, **kwargs) -> Any:
            if inspect.iscoroutinefunction(func):
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return await func(*bound.args, **bound.kwargs)
            return self._run(*args, **kwargs)

    tool = WrapperTool(name=name, description=description)
    for key, value in metadata.items():
        if hasattr(tool, key):
            setattr(tool, key, value)

    return tool


def _create_composite_tool(
    tools: list[BaseTool],
    name: str,
    description: str,
    selector: Optional[Callable] = None
) -> BaseTool:
    """Create a composite tool from multiple tools.

    Args:
        tools: List of tools
        name: Composite tool name
        description: Composite tool description
        selector: Function to select which tool to use

    Returns:
        Composite BaseTool
    """
    class CompositeTool(BaseTool):
        name: str = name
        description: str = description

        def _run(self, *args, **kwargs) -> Any:
            if selector:
                selected = selector(kwargs)
                for tool in tools:
                    if tool.name == selected:
                        return tool.invoke(kwargs)

            raise ValueError("No selector provided for composite tool")

        async def _arun(self, *args, **kwargs) -> Any:
            if selector:
                selected = selector(kwargs)
                for tool in tools:
                    if tool.name == selected:
                        return await tool.ainvoke(kwargs)

            raise ValueError("No selector provided for composite tool")

    return CompositeTool(name=name, description=description)


def create_tool_from_spec(
    spec: dict[str, Any] | ToolSpec,
    handler: Optional[Callable] = None
) -> BaseTool:
    """Convenience function to create a tool from a spec dict or ToolSpec.

    Args:
        spec: Specification dict or ToolSpec
        handler: Optional handler function to execute

    Returns:
        BaseTool instance
    """
    if isinstance(spec, dict):
        spec = ToolSpec(**spec)
    return _create_tool_from_spec(spec, handler)