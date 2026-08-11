"""Dynamic Tool Generator Module

Generates executable tools from code strings, enabling LLM to create and run dynamic tools.
"""

from typing import Any, Callable, Optional
from dataclasses import dataclass
import inspect

from langchain_core.tools import BaseTool


SAFE_BUILTINS = {
    'print': print,
    'len': len,
    'range': range,
    'str': str,
    'int': int,
    'float': float,
    'bool': bool,
    'list': list,
    'dict': dict,
    'tuple': tuple,
    'set': set,
    'frozenset': frozenset,
    'min': min,
    'max': max,
    'sum': sum,
    'abs': abs,
    'round': round,
    'sorted': sorted,
    'reversed': reversed,
    'enumerate': enumerate,
    'zip': zip,
    'map': map,
    'filter': filter,
    'any': any,
    'all': all,
    'isinstance': isinstance,
    'issubclass': issubclass,
    'type': type,
    'getattr': getattr,
    'setattr': setattr,
    'hasattr': hasattr,
    'callable': callable,
    'open': open,
    'json': __import__('json'),
    'math': __import__('math'),
    're': __import__('re'),
    'datetime': __import__('datetime'),
    'timedelta': __import__('datetime').timedelta,
    'date': __import__('datetime').date,
    'time': __import__('datetime').time,
}


@dataclass
class DynamicToolSpec:
    name: str
    description: str
    code: str
    parameters: Optional[dict[str, Any]] = None
    return_field: str = "result"
    examples: Optional[list[dict[str, Any]]] = None


class SafeCodeExecutor:
    """Safe code executor with restricted builtins."""

    @staticmethod
    def execute(code: str, params: dict[str, Any], return_field: str = "result") -> Any:
        """Execute code with parameters in a safe namespace.

        Args:
            code: Python code to execute (should set 'result' variable)
            params: Parameters to inject into execution namespace
            return_field: Name of variable to return (default: 'result')

        Returns:
            Value of the return_field variable after execution
        """
        namespace = {
            '__builtins__': SAFE_BUILTINS,
        }
        namespace.update(params)

        try:
            exec(code, namespace)

            result = namespace.get(return_field)
            if result is None and return_field != "result":
                result = namespace.get("result")

            return result
        except Exception as e:
            raise RuntimeError(f"Code execution failed: {e}\nCode:\n{code}") from e

    @staticmethod
    def validate_code(code: str) -> tuple[bool, Optional[str]]:
        """Validate code for safety and syntax.

        Args:
            code: Python code to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        dangerous_patterns = [
            'import os',
            'import sys',
            'import subprocess',
            'import socket',
            '__import__',
            'open(',
            'file(',
            'eval(',
            'exec(',
            'compile(',
            'input(',
            'exit(',
            'quit(',
            'breakpoint(',
            'reload(',
            'lambda: __import__',
            'os.',
            'sys.',
            'subprocess.',
            'socket.',
        ]

        for pattern in dangerous_patterns:
            if pattern in code:
                return False, f"Dangerous pattern detected: {pattern}"

        try:
            compile(code, '<string>', 'exec')
            return True, None
        except SyntaxError as e:
            return False, f"Syntax error: {e}"


class DynamicToolFactory:
    """Factory for creating dynamic executable tools."""

    def __init__(self, validate_code: bool = True):
        self.validate_code = validate_code

    def create_from_spec(self, spec: DynamicToolSpec | dict[str, Any]) -> BaseTool:
        """Create a dynamic tool from specification.

        Args:
            spec: DynamicToolSpec or dict with tool definition

        Returns:
            BaseTool instance ready to execute

        Example:
            >>> spec = {
            ...     "name": "add_numbers",
            ...     "description": "Add two numbers",
            ...     "parameters": {"a": "integer", "b": "integer"},
            ...     "code": "result = a + b",
            ... }
            >>> tool = factory.create_from_spec(spec)
            >>> tool.invoke({"a": 5, "b": 3})
            8
        """
        if isinstance(spec, dict):
            spec = DynamicToolSpec(**spec)

        if self.validate_code:
            is_valid, error = SafeCodeExecutor.validate_code(spec.code)
            if not is_valid:
                raise ValueError(f"Invalid code: {error}")

        return _create_dynamic_tool(spec)


def _create_dynamic_tool(spec: DynamicToolSpec) -> BaseTool:
    """Create a dynamic tool from spec.

    Args:
        spec: DynamicToolSpec

    Returns:
        BaseTool with code execution capability
    """
    from pydantic import BaseModel as PydanticBaseModel, Field, create_model

    tool_name = spec.name
    tool_desc = spec.description
    code = spec.code
    params_schema = spec.parameters or {}
    return_field = spec.return_field

    args_schema_class = PydanticBaseModel
    if params_schema:
        field_definitions = {}
        for param_name, param_info in params_schema.items():
            ptype = param_info if isinstance(param_info, str) else param_info.get('type', 'string')
            default = param_info.get('default') if isinstance(param_info, dict) else None
            description = param_info.get('description', '') if isinstance(param_info, dict) else ''

            type_map = {
                'string': str,
                'integer': int,
                'number': float,
                'boolean': bool,
                'array': list,
                'object': dict
            }

            field_type = type_map.get(ptype, str)
            if default is None:
                field_definitions[param_name] = (field_type, ...)
            else:
                field_definitions[param_name] = (field_type, Field(default=default, description=description))

        if field_definitions:
            args_schema_class = create_model('DynamicToolArgs', **field_definitions)

    class _DynamicTool(BaseTool):
        name: str = tool_name
        description: str = tool_desc
        args_schema: type[PydanticBaseModel] = args_schema_class

        def _run(self, *args, **kwargs) -> Any:
            return SafeCodeExecutor.execute(code, kwargs, return_field)

        async def _arun(self, *args, **kwargs) -> Any:
            return self._run(*args, **kwargs)

    return _DynamicTool(name=tool_name, description=tool_desc)


def create_dynamic_tool(spec: DynamicToolSpec | dict[str, Any]) -> BaseTool:
    """Convenience function to create a dynamic tool.

    Args:
        spec: Tool specification

    Returns:
        BaseTool instance
    """
    factory = DynamicToolFactory()
    return factory.create_from_spec(spec)