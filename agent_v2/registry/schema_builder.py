"""Tool Schema Builder

Builds and validates tool schemas.
Following the architecture: Tool Registry + Capability Resolver
"""

from typing import Any, Optional
import json

from langchain_core.tools import BaseTool


class SchemaBuilder:
    """Builder for tool schemas
    
    Converts tool definitions to schema format for:
    - LLM tool binding
    - Tool validation
    - Documentation generation
    """
    
    @staticmethod
    def build_schema(tool: BaseTool) -> dict:
        """Build schema from tool
        
        Args:
            tool: BaseTool instance
            
        Returns:
            Schema dict
        """
        name = getattr(tool, 'name', 'unnamed')
        description = getattr(tool, 'description', '')
        
        args_schema = getattr(tool, 'args_schema', None)
        if args_schema:
            if hasattr(args_schema, 'model_json_schema'):
                schema = args_schema.model_json_schema()
            elif hasattr(args_schema, 'schema'):
                schema = args_schema.schema()
            else:
                schema = {}
        else:
            schema = {"type": "object", "properties": {}}
        
        return {
            "name": name,
            "description": description,
            "parameters": schema,
        }
    
    @staticmethod
    def validate_params(tool: BaseTool, params: dict) -> tuple[bool, Optional[str]]:
        """Validate parameters against tool schema
        
        Args:
            tool: BaseTool instance
            params: Parameters dict
            
        Returns:
            Tuple of (valid, error_message)
        """
        schema = SchemaBuilder.build_schema(tool)
        props = schema.get("parameters", {}).get("properties", {})
        
        required = schema.get("parameters", {}).get("required", [])
        
        for req in required:
            if req not in params:
                return False, f"Missing required parameter: {req}"
        
        for param_name, param_value in params.items():
            if param_name not in props:
                continue
            
            param_schema = props[param_name]
            param_type = param_schema.get("type")
            
            if param_type == "string" and not isinstance(param_value, str):
                return False, f"Parameter {param_name} must be string"
            elif param_type == "integer" and not isinstance(param_value, int):
                return False, f"Parameter {param_name} must be integer"
            elif param_type == "number" and not isinstance(param_value, (int, float)):
                return False, f"Parameter {param_name} must be number"
            elif param_type == "boolean" and not isinstance(param_value, bool):
                return False, f"Parameter {param_name} must be boolean"
            elif param_type == "array" and not isinstance(param_value, list):
                return False, f"Parameter {param_name} must be array"
            elif param_type == "object" and not isinstance(param_value, dict):
                return False, f"Parameter {param_name} must be object"
        
        return True, None
    
    @staticmethod
    def get_tool_description(tool: BaseTool) -> str:
        """Get formatted tool description
        
        Args:
            tool: BaseTool instance
            
        Returns:
            Formatted description
        """
        schema = SchemaBuilder.build_schema(tool)
        
        lines = [f"Tool: {schema['name']}"]
        lines.append(f"Description: {schema['description']}")
        
        params = schema.get("parameters", {}).get("properties", {})
        if params:
            lines.append("Parameters:")
            for param_name, param_info in params.items():
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                lines.append(f"  - {param_name} ({param_type}): {param_desc}")
        
        return "\n".join(lines)