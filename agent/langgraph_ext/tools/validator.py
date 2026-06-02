"""Tool Validator Module

Provides parameter validation and schema validation for registered tools.
"""

from dataclasses import dataclass
from typing import Any, Optional
import json
import re

from .registry import ToolRegistry, RegisteredTool


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]
    warnings: list[str]
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0
    
    def merge(self, other: 'ValidationResult') -> 'ValidationResult':
        """Merge two validation results.
        
        Args:
            other: Another ValidationResult
            
        Returns:
            Merged ValidationResult
        """
        return ValidationResult(
            is_valid=self.is_valid and other.is_valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings
        )


class ToolValidator:
    """Validates tool parameters and schemas.
    
    Features:
    - JSON Schema validation
    - Type checking
    - Required field validation
    - Custom validation rules
    - Cross-field validation
    """
    
    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry
        self._custom_validators: dict[str, list[callable]] = {}
    
    def register_custom_validator(
        self,
        tool_name: str,
        validator: callable
    ) -> None:
        """Register a custom validator function for a tool.
        
        Args:
            tool_name: Tool name
            validator: Validator function that takes (value, **kwargs) and returns ValidationResult
        """
        if tool_name not in self._custom_validators:
            self._custom_validators[tool_name] = []
        self._custom_validators[tool_name].append(validator)
    
    def validate_params(
        self,
        tool_name: str,
        params: dict[str, Any],
        required_params: Optional[list[str]] = None,
        schema: Optional[dict] = None
    ) -> ValidationResult:
        """Validate tool parameters.
        
        Args:
            tool_name: Name of the tool
            params: Parameters to validate
            required_params: List of required parameter names
            schema: JSON Schema for validation
            
        Returns:
            ValidationResult with validation status
        """
        errors = []
        warnings = []
        
        if self.registry:
            registered = self.registry.get_registered_tool(tool_name)
            if not registered:
                return ValidationResult(
                    is_valid=False,
                    errors=[f"Tool '{tool_name}' not found in registry"],
                    warnings=[]
                )
            
            if not registered.enabled:
                errors.append(f"Tool '{tool_name}' is disabled")
            
            if registered.metadata.deprecated:
                warnings.append(
                    f"Tool '{tool_name}' is deprecated. "
                    f"{registered.metadata.deprecation_message or 'Please consider using an alternative.'}"
                )
        
        required_params = required_params or []
        for param in required_params:
            if param not in params:
                errors.append(f"Required parameter '{param}' is missing")
        
        if schema:
            schema_errors = self._validate_with_schema(params, schema)
            errors.extend(schema_errors)
        
        custom_validators = self._custom_validators.get(tool_name, [])
        for validator in custom_validators:
            try:
                result = validator(params)
                if isinstance(result, ValidationResult):
                    errors.extend(result.errors)
                    warnings.extend(result.warnings)
            except Exception as e:
                errors.append(f"Custom validator failed: {str(e)}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def _validate_with_schema(
        self,
        params: dict[str, Any],
        schema: dict[str, Any]
    ) -> list[str]:
        """Validate parameters against a JSON Schema.
        
        Args:
            params: Parameters to validate
            schema: JSON Schema
            
        Returns:
            List of error messages
        """
        errors = []
        
        if 'type' in schema:
            expected_type = schema['type']
            for key, value in params.items():
                if not self._check_type(value, expected_type):
                    errors.append(
                        f"Parameter '{key}' has incorrect type. "
                        f"Expected {expected_type}, got {type(value).__name__}"
                    )
        
        if 'properties' in schema:
            for prop_name, prop_schema in schema['properties'].items():
                if prop_name in params:
                    prop_errors = self._validate_property(prop_name, params[prop_name], prop_schema)
                    errors.extend(prop_errors)
        
        if 'required' in schema:
            for required in schema['required']:
                if required not in params:
                    errors.append(f"Required property '{required}' is missing")
        
        return errors
    
    def _validate_property(
        self,
        name: str,
        value: Any,
        schema: dict[str, Any]
    ) -> list[str]:
        """Validate a single property against its schema.
        
        Args:
            name: Property name
            value: Property value
            schema: Property schema
            
        Returns:
            List of error messages
        """
        errors = []
        
        if 'type' in schema:
            if not self._check_type(value, schema['type']):
                errors.append(
                    f"Property '{name}' has incorrect type. "
                    f"Expected {schema['type']}, got {type(value).__name__}"
                )
                return errors
        
        if 'minLength' in schema and isinstance(value, str):
            if len(value) < schema['minLength']:
                errors.append(f"Property '{name}' must be at least {schema['minLength']} characters")
        
        if 'maxLength' in schema and isinstance(value, str):
            if len(value) > schema['maxLength']:
                errors.append(f"Property '{name}' must be at most {schema['maxLength']} characters")
        
        if 'minimum' in schema and isinstance(value, (int, float)):
            if value < schema['minimum']:
                errors.append(f"Property '{name}' must be at least {schema['minimum']}")
        
        if 'maximum' in schema and isinstance(value, (int, float)):
            if value > schema['maximum']:
                errors.append(f"Property '{name}' must be at most {schema['maximum']}")
        
        if 'pattern' in schema and isinstance(value, str):
            if not re.match(schema['pattern'], value):
                errors.append(f"Property '{name}' does not match pattern '{schema['pattern']}'")
        
        if 'enum' in schema:
            if value not in schema['enum']:
                errors.append(f"Property '{name}' must be one of {schema['enum']}")
        
        return errors
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type.
        
        Args:
            value: Value to check
            expected_type: Expected type name
            
        Returns:
            True if type matches
        """
        type_map = {
            'string': str,
            'number': (int, float),
            'integer': int,
            'boolean': bool,
            'array': list,
            'object': dict,
            'null': type(None)
        }
        
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        
        return isinstance(value, expected)
    
    def validate_schema(self, schema: dict[str, Any]) -> ValidationResult:
        """Validate a JSON Schema itself.
        
        Args:
            schema: Schema to validate
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        if 'type' in schema and schema['type'] not in ('string', 'number', 'integer', 'boolean', 'array', 'object', 'null'):
            errors.append(f"Invalid schema type: {schema['type']}")
        
        if 'properties' in schema:
            if not isinstance(schema['properties'], dict):
                errors.append("'properties' must be an object")
            else:
                for prop_name, prop_schema in schema['properties'].items():
                    prop_result = self.validate_schema(prop_schema)
                    errors.extend([f"{prop_name}.{e}" for e in prop_result.errors])
                    warnings.extend([f"{prop_name}.{w}" for w in prop_result.warnings])
        
        if 'required' in schema:
            if not isinstance(schema['required'], list):
                errors.append("'required' must be an array")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )


def validate_tool_params(
    tool_name: str,
    params: dict[str, Any],
    registry: Optional[ToolRegistry] = None,
    **kwargs
) -> ValidationResult:
    """Convenience function to validate tool parameters.
    
    Args:
        tool_name: Tool name
        params: Parameters to validate
        registry: Optional registry to use
        **kwargs: Additional validation options
        
    Returns:
        ValidationResult
    """
    validator = ToolValidator(registry)
    return validator.validate_params(tool_name, params, **kwargs)