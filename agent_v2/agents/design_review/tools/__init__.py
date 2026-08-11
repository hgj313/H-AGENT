"""Design Review Tools Module

Collects all tools for design review capability.
Following the architecture: Tool = capability execution
"""

from .read_file import read_file_tool, ReadFileTool
from .analyze_prototype import analyze_prototype
from .analyze_prd import analyze_prd


def get_all_tools():
    """Get all design review tools
    
    Returns:
        List of all tools
    """
    return [
        read_file_tool,
        analyze_prototype,
        analyze_prd,
    ]


__all__ = [
    "read_file_tool",
    "ReadFileTool",
    "analyze_prototype",
    "analyze_prd",
    "get_all_tools",
]