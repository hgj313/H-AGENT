"""Flow Router Node

Implements Flow Router following the architecture document:
- Central control flow router
- Maps next_action to target nodes
- Final authority for routing decisions

Architecture: Graph管生命周期，Router管跳转
"""

from typing import Literal, TypedDict


class FlowRouterNode:
    """Flow router node for control flow decisions
    
    Responsibilities:
    1. Map next_action to target node
    2. Handle loop control
    3. Determine termination
    
    Routing table:
    - continue → agent_node (loop back)
    - retry → retry_handler
    - human_review → human_review_node
    - finish → END
    """
    
    ROUTES = {
        "continue": "agent_node",
        "retry": "retry_handler",
        "human_review": "human_review",
        "finish": "finished",
        "tool": "tool_node",
    }
    
    def __init__(self, custom_routes: dict[str, str] = None):
        """Initialize flow router
        
        Args:
            custom_routes: Optional custom routing table
        """
        self.routes = custom_routes or self.ROUTES.copy()
    
    def __call__(self, state: dict) -> dict:
        """Execute flow routing
        
        Args:
            state: Current state with next_action
            
        Returns:
            State with routing info
        """
        return self.route(state)
    
    def route(self, state: dict) -> dict:
        """Determine routing based on next_action
        
        Args:
            state: State with next_action
            
        Returns:
            State with target_node set
        """
        action = state.get("next_action", "finish")
        target = self.routes.get(action, "finished")
        
        state["metadata"]["target_node"] = target
        state["metadata"]["routed_action"] = action
        
        return state
    
    def get_next_node(self, state: dict) -> str:
        """Get next node name
        
        Args:
            state: Current state
            
        Returns:
            Next node name
        """
        action = state.get("next_action", "finish")
        return self.routes.get(action, "finished")


def create_flow_router_node(
    custom_routes: dict[str, str] = None
) -> FlowRouterNode:
    """Factory function to create flow router node
    
    Args:
        custom_routes: Optional custom routes
        
    Returns:
        FlowRouterNode instance
    """
    return FlowRouterNode(custom_routes=custom_routes)


def flow_router_node(state: dict) -> dict:
    """Standalone flow router function
    
    Args:
        state: Current state
        
    Returns:
        State with target_node
    """
    ROUTES = {
        "continue": "agent_node",
        "retry": "retry_handler",
        "human_review": "human_review",
        "finish": "finished",
        "tool": "tool_node",
    }
    
    action = state.get("next_action", "finish")
    target = ROUTES.get(action, "finished")
    
    state["metadata"]["target_node"] = target
    
    return state


def create_conditional_flow_edges(
    routes_map: dict[str, str] = None
):
    """Create conditional edges function for flow router
    
    Args:
        routes_map: Custom routing map
        
    Returns:
        Conditional edges function
    """
    ROUTES = routes_map or {
        "continue": "agent_node",
        "retry": "retry_handler",
        "human_review": "human_review",
        "finish": "finished",
        "tool": "tool_node",
    }
    
    def route_func(state: dict) -> str:
        action = state.get("next_action", "finish")
        return ROUTES.get(action, "finished")
    
    return route_func