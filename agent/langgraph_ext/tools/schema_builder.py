"""Schema Builder Module

Automatically builds JSON Schema and Pydantic models from Python function signatures and type annotations.
Supports bidirectional conversion: Function Signature <-> Pydantic Model <-> JSON Schema
"""

import inspect
from typing import Any, Callable, Union, List, Dict, get_type_hints, Optional, ForwardRef
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator


@dataclass
class TypeMapping:
    python_type: type
    json_type: str
    default_factory: Optional[Callable] = None


class SchemaBuilder:
    """Automatically build Pydantic models and JSON Schema from Python function signatures.

    Features:
    - Extract parameters and type annotations from function signatures
    - Handle complex generics (List[T], Dict[K,V], Optional[T], Union[T1,T2])
    - Bidirectional conversion: Pydantic model <-> JSON Schema
    - Custom validation rules
    """

    TYPE_MAPPING: dict[type, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    def __init__(self):
        self._custom_type_mappings: dict[type, str] = {}

    def register_type_mapping(self, python_type: type, json_type: str) -> None:
        """Register a custom type mapping.

        Args:
            python_type: Python type
            json_type: JSON Schema type string
        """
        self._custom_type_mappings[python_type] = json_type

    @classmethod
    def from_callable(cls, func: Callable) -> type[BaseModel]:
        """Automatically generate a Pydantic model class from a function.

        Args:
            func: The function to be registered as a tool

        Returns:
            Pydantic BaseModel subclass containing the function's parameter definitions

        Example:
            >>> def add_numbers(a: int, b: int = 10) -> int:
            ...     return a + b
            >>>
            >>> model = SchemaBuilder.from_callable(add_numbers)
            >>> print(model.model_fields)
            {'a': Field(annotation=int, required=True), 'b': Field(annotation=int, default=10)}
        """
        return cls().build_model_from_function(func)

    def build_model_from_function(self, func: Callable) -> type[BaseModel]:
        """Build a Pydantic model (instance method version).

        Args:
            func: The function to process

        Returns:
            Pydantic BaseModel subclass
        """
        from pydantic import create_model

        sig = inspect.signature(func)

        try:
            type_hints = get_type_hints(func)
        except Exception:
            type_hints = self._extract_type_hints_fallback(func)

        field_definitions = {}

        for name, param in sig.parameters.items():
            python_type = type_hints.get(name, str)
            mapped_type = self._map_python_type(python_type)

            if param.default != inspect.Parameter.empty:
                default = param.default
                field_definitions[name] = (mapped_type, default)
            else:
                field_definitions[name] = mapped_type

        model_name = f"{func.__name__}Params"
        return create_model(model_name, **field_definitions)

    def build_schema_from_function(self, func: Callable) -> dict[str, Any]:
        """Generate JSON Schema from a function.

        Args:
            func: The function to process

        Returns:
            JSON Schema dictionary
        """
        sig = inspect.signature(func)

        try:
            type_hints = get_type_hints(func)
        except Exception:
            type_hints = {}

        properties = {}
        required = []

        for name, param in sig.parameters.items():
            python_type = type_hints.get(name, str)
            prop_schema = self._python_type_to_json_schema(python_type)

            if param.default != inspect.Parameter.empty:
                prop_schema["default"] = param.default
            else:
                required.append(name)

            if name in type_hints and (doc := func.__doc__):
                desc = self._extract_param_description(doc, name)
                if desc:
                    prop_schema["description"] = desc

            properties[name] = prop_schema

        return {
            "type": "object",
            "properties": properties,
            "required": required if required else None
        }

    def build_schema_from_model(self, model: type[BaseModel]) -> dict[str, Any]:
        """Generate JSON Schema from a Pydantic model.

        Args:
            model: Pydantic model class

        Returns:
            JSON Schema dictionary
        """
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        for name, field_info in model.model_fields.items():
            prop = self._pydantic_field_to_json_schema(field_info)

            if field_info.default is not None and field_info.default != ...:
                prop["default"] = field_info.default

            if field_info.description:
                prop["description"] = field_info.description

            schema["properties"][name] = prop

            if field_info.is_required():
                schema["required"].append(name)

        if not schema["required"]:
            del schema["required"]

        return schema

    def build_model_from_schema(self, schema: dict[str, Any], model_name: str = "SchemaModel") -> type[BaseModel]:
        """Build a Pydantic model from JSON Schema.

        Args:
            schema: JSON Schema dictionary
            model_name: Model name

        Returns:
            Pydantic BaseModel subclass
        """
        attrs = {}

        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])

        for param_name, param_schema in properties.items():
            ptype = param_schema.get("type", "string")
            default = param_schema.get("default", ...)

            if param_name in required_fields and default is ...:
                default = ...

            description = param_schema.get("description", "")

            type_map = {
                "string": str,
                "integer": int,
                "number": float,
                "boolean": bool,
                "array": list,
                "object": dict
            }

            field_type = type_map.get(ptype, str)
            attrs[param_name] = (field_type, Field(default=default, description=description))

        return type(model_name, (BaseModel,), attrs)

    def _map_python_type(self, python_type: Any) -> type:
        """Map Python types to actual usable types.

        Args:
            python_type: Python type annotation

        Returns:
            Type usable for Pydantic Field
        """
        origin = getattr(python_type, '__origin__', None)

        if origin is list:
            args = python_type.__args__ if hasattr(python_type, '__args__') else (Any,)
            item_type = self._map_python_type(args[0])
            return List[item_type]

        if origin is Union:
            args = list(python_type.__args__) if hasattr(python_type, '__args__') else []
            non_none_args = [a for a in args if a is not type(None)]

            if len(non_none_args) == 1 and type(None) in args:
                return Optional[self._map_python_type(non_none_args[0])]

            return Union[tuple(self._map_python_type(a) for a in non_none_args)]

        if origin is dict:
            args = python_type.__args__ if hasattr(python_type, '__args__') else (Any, Any)
            key_type = self._map_python_type(args[0])
            val_type = self._map_python_type(args[1]) if len(args) > 1 else Any
            return Dict[key_type, val_type]

        if isinstance(python_type, type):
            return python_type

        return str

    def _python_type_to_json_schema(self, python_type: Any) -> dict[str, Any]:
        """Convert Python types to JSON Schema properties.

        Args:
            python_type: Python type annotation

        Returns:
            JSON Schema property dictionary
        """
        origin = getattr(python_type, '__origin__', None)

        if origin is list:
            items_schema = {}
            if hasattr(python_type, '__args__') and python_type.__args__:
                items_schema = self._python_type_to_json_schema(python_type.__args__[0])
            return {"type": "array", "items": items_schema or {"type": "string"}}

        if origin is Union:
            args = list(python_type.__args__) if hasattr(python_type, '__args__') else []
            non_none_args = [a for a in args if a is not type(None)]

            if len(non_none_args) == 1 and type(None) in args:
                return self._python_type_to_json_schema(non_none_args[0])

            return {"type": "string"}

        if origin is dict:
            return {"type": "object"}

        if python_type in self.TYPE_MAPPING:
            return {"type": self.TYPE_MAPPING[python_type]}

        if python_type in self._custom_type_mappings:
            return {"type": self._custom_type_mappings[python_type]}

        if isinstance(python_type, type):
            return {"type": "string"}

        return {"type": "string"}

    def _pydantic_field_to_json_schema(self, field_info) -> dict[str, Any]:
        """Convert Pydantic FieldInfo to JSON Schema properties.

        Args:
            field_info: Pydantic model field information

        Returns:
            JSON Schema property dictionary
        """
        annotation = field_info.annotation

        origin = getattr(annotation, '__origin__', None)

        if origin is list:
            return {"type": "array", "items": {"type": "string"}}

        if origin is Union:
            args = list(annotation.__args__) if hasattr(annotation, '__args__') else []
            non_none_args = [a for a in args if a is not type(None)]

            if non_none_args:
                first_type = non_none_args[0]
                return self._python_type_to_json_schema(first_type)

            return {"type": "string"}

        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }

        if annotation in type_map:
            return {"type": type_map[annotation]}

        return {"type": "string"}

    def _extract_type_hints_fallback(self, func: Callable) -> dict[str, type]:
        """Fallback method: use inspect to extract type annotations.

        Args:
            func: Function object

        Returns:
            Mapping of parameter names to types
        """
        sig = inspect.signature(func)
        hints = {}

        for name, param in sig.parameters.items():
            if param.annotation != inspect.Parameter.empty:
                hints[name] = param.annotation
            else:
                hints[name] = Any

        return hints

    def _extract_param_description(self, docstring: str, param_name: str) -> Optional[str]:
        """Extract parameter description from docstring.

        Args:
            docstring: Function docstring
            param_name: Parameter name

        Returns:
            Parameter description or None
        """
        if not docstring:
            return None

        lines = docstring.split('\n')
        in_args_section = False

        for line in lines:
            stripped = line.strip()

            if stripped.lower().startswith('args:') or stripped.lower().startswith('arguments:'):
                in_args_section = True
                continue

            if stripped.lower().startswith(('returns:', 'examples:', 'raises:')):
                in_args_section = False
                continue

            if in_args_section and ':' in stripped:
                parts = stripped.split(':', 1)
                if parts[0].strip() == param_name:
                    return parts[1].strip()

        return None


def auto_build_schema(func: Callable) -> dict[str, Any]:
    """Convenience function: automatically build JSON Schema from a function.

    Args:
        func: The function to process

    Returns:
        JSON Schema dictionary

    Example:
        >>> def search_users(query: str, limit: int = 20) -> list[dict]:
        ...     '''Search users by query.'''
        ...     pass
        >>>
        >>> schema = auto_build_schema(search_users)
        >>> print(schema)
        {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'limit': {'type': 'integer', 'default': 20}
            },
            'required': ['query']
        }
    """
    return SchemaBuilder().build_schema_from_function(func)


def auto_build_model(func: Callable) -> type[BaseModel]:
    """Convenience function: automatically build Pydantic model from a function.

    Args:
        func: The function to process

    Returns:
        Pydantic BaseModel subclass

    Example:
        >>> def add_numbers(a: int, b: int = 10) -> int:
        ...     pass
        >>>
        >>> Model = auto_build_model(add_numbers)
        >>> instance = Model(a=5)
        >>> print(instance.a, instance.b)
        5 10
    """
    return SchemaBuilder.from_callable(func)


__all__ = [
    "SchemaBuilder",
    "auto_build_schema",
    "auto_build_model",
]