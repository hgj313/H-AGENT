"""Read File Node

Design review agent node for file reading functionality.
Follows the architecture: Node = business logic
"""

from typing import Literal
from langchain_core.messages import AIMessage, ToolMessage

from ..states.dr_state import DesignReviewState


def read_file_node(state: DesignReviewState) -> dict:
    """Read file node handler
    
    Processes file reading tool calls and returns results.
    
    Args:
        state: Current state with messages
        
    Returns:
        Updated state with tool results
    """
    messages = state.get("messages", [])
    last_msg = messages[-1] if messages else None
    
    if not isinstance(last_msg, AIMessage):
        return state
    
    file_path = None
    tool_call_id = None
    
    for tc in getattr(last_msg, "tool_calls", []):
        if tc.get("name") == "read_file":
            file_path = tc.get("args", {}).get("file_path")
            tool_call_id = tc.get("id")
            break
    
    if not file_path:
        return state
    
    from ..tools.read_file.read_file import read_file_tool
    result = read_file_tool.invoke({"file_path": file_path})
    
    return {
        "messages": messages + [ToolMessage(content=result, tool_call_id=tool_call_id)],
        "llm_calls": state.get("llm_calls", 0),
    }


class ReadFileNode:
    """Read file node class for more complex scenarios
    
    Use this class when you need:
    - Custom initialization
    - Multiple tool bindings
    - State management
    """
    
    def __init__(self, tool=None):
        self.tool = tool
    
    def __call__(self, state: DesignReviewState) -> dict:
        return read_file_node(state)
    
    def execute(self, state: DesignReviewState, file_path: str) -> dict:
        """Execute read file with specific path
        
        Args:
            state: Current state
            file_path: File path to read
            
        Returns:
            Execution result
        """
        if not self.tool:
            from ..tools.read_file.read_file import read_file_tool
            self.tool = read_file_tool
        
        result = self.tool.invoke({"file_path": file_path})
        
        return {
            "tool_results": {
                **state.get("tool_results", {}),
                "read_file": {"success": True, "content": result}
            }
        }