"""Design Review Capability Module

Implements the design review capability following the architecture:
- Graph = orchestration
- Node = business logic  
- State = source of truth

This module contains all design review specific components:
- states: State definitions
- nodes: Business logic nodes
- tools: Capability tools
"""

from .states import (
    DesignReviewState,
    create_design_review_state,
    detect_image_in_message,
)

from .nodes import (
    ReadFileNode,
    read_file_node,
    AnalyzePrototypeNode,
    analyze_prototype_node,
)

from .tools import (
    read_file_tool,
    analyze_prototype,
    analyze_prd,
    get_all_tools,
)


class DesignReviewCapability:
    """Design review capability class
    
    Encapsulates all design review related components.
    Following the capability pattern from architecture doc.
    """
    
    def __init__(self):
        self.state_class = DesignReviewState
        self.nodes = {
            "read_file": read_file_node,
            "analyze_prototype": analyze_prototype_node,
        }
        self.tools = get_all_tools()
    
    def get_tools(self):
        """Get capability tools"""
        return self.tools
    
    def get_nodes(self):
        """Get capability nodes"""
        return self.nodes
    
    def create_state(self, user_goal: str = "", thread_id: str = None):
        """Create initial state for this capability"""
        return create_design_review_state(
            user_goal=user_goal,
            thread_id=thread_id
        )


__all__ = [
    "DesignReviewState",
    "create_design_review_state",
    "detect_image_in_message",
    "ReadFileNode",
    "read_file_node",
    "AnalyzePrototypeNode",
    "analyze_prototype_node",
    "read_file_tool",
    "analyze_prototype",
    "analyze_prd",
    "get_all_tools",
    "DesignReviewCapability",
]