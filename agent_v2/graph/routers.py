"""Router Module

Implements deterministic routing following the architecture document:
- Router = final authority (not LLM)
- LLM = decision suggestion

This module contains all routing logic that determines node transitions
based on state, following the FSM pattern.

Key principles:
1. Routing is deterministic - no randomness
2. Routes are determined by state, not hardcoded if/else
3. Clear separation between business logic (nodes) and control flow (routers)
"""

from typing import Literal, Callable, Optional
from .state import AgentState, DesignReviewState


class BaseRouter:
    """Base router class following the architecture pattern
    
    All routers should inherit from this class and implement route() method.
    Routers are pure deterministic functions - no LLM calls, no randomness.
    """
    
    def __init__(self):
        self.routes: dict[str, str] = {}
    
    def route(self, state: dict) -> str:
        """Determine next node based on state
        
        Args:
            state: Current state
            
        Returns:
            Next node name
        """
        raise NotImplementedError("Subclasses must implement route()")
    
    def _get_route(self, state: dict, key: str, default: str) -> str:
        """Helper to get route with default fallback"""
        return self.routes.get(state.get(key, ""), default)


class IntentRouter(BaseRouter):
    """Intent Router - classifies user intent to capability domain
    
    This is the first router in the pipeline, determining which
    capability domain the request belongs to.
    
    Supported capabilities:
    - coding: Code generation, review, modification
    - research: Information retrieval, analysis
    - writing: Content creation, editing
    - design_review: Design document review (existing module)
    - analytics: Data analysis, visualization
    """
    
    def __init__(self):
        super().__init__()
        self.routes = {
            "coding": "coding_agent",
            "research": "research_agent",
            "writing": "writing_agent",
            "design_review": "design_review_agent",
            "analytics": "analytics_agent",
        }
    
    def route(self, state: AgentState) -> Literal[
        "coding_agent", "research_agent", "writing_agent",
        "design_review_agent", "analytics_agent"
    ]:
        """Route based on detected intent
        
        Args:
            state: Current state with user_goal
            
        Returns:
            Agent node name
        """
        capability = state.get("capability", "unknown")
        return self.routes.get(capability, "unknown_capability")


class CapabilityRouter(BaseRouter):
    """Capability Router - routes to specific capability agent
    
    After intent routing, this router selects the appropriate
    agent node based on capability domain.
    """
    
    def __init__(self):
        super().__init__()
        self.routes = {
            "coding": "coding_agent",
            "research": "research_agent",
            "writing": "writing_agent",
            "design_review": "design_review_capability",
            "analytics": "analytics_agent",
        }
    
    def route(self, state: AgentState) -> str:
        """Route to capability agent"""
        capability = state.get("capability", "")
        return self.routes.get(capability, "default_agent")


class FlowRouter(BaseRouter):
    """Flow Router - controls main execution flow
    
    This is the central control router that determines:
    - continue: Loop back to agent
    - retry: Retry current operation
    - human_review: Wait for human approval
    - finish: End execution
    
    Following the architecture: Graph管生命周期，Router管跳转
    """
    
    def __init__(self):
        super().__init__()
        self.routes = {
            "continue": "continue_node",
            "retry": "retry_handler",
            "human_review": "human_review",
            "finish": "finished",
            "tool": "tool_node",
        }
    
    def route(self, state: AgentState) -> str:
        """Route based on next_action in state
        
        Args:
            state: State with next_action field
            
        Returns:
            Next control flow node
        """
        action = state.get("next_action", "finish")
        return self.routes.get(action, "finish")


class JudgeRouter(BaseRouter):
    """Judge Router - determines quality and termination
    
    Evaluates execution results and decides whether to:
    - Continue execution
    - Retry (with incremented retry count)
    - Request human review
    - Finish execution
    
    This implements the Result Judge pattern from architecture doc.
    """
    
    MAX_RETRIES: int = 3
    
    def __init__(self):
        super().__init__()
    
    def route(self, state: AgentState) -> Literal["continue", "retry", "human_review", "finish"]:
        """Judge execution result and determine next action
        
        Args:
            state: State with working_memory, tool_results, error
            
        Returns:
            Next action
        """
        # Check for errors
        if state.get("error"):
            retry_count = state.get("retry_count", 0)
            if retry_count < self.MAX_RETRIES:
                return "retry"
            return "human_review"
        
        # Check if final response is ready
        if state.get("final_response"):
            return "finish"
        
        # Check for more work
        working_memory = state.get("working_memory", {})
        if working_memory.get("needs_continuation"):
            return "continue"
        
        # Default: continue with work
        return "continue"
    
    def evaluate_result(self, state: AgentState) -> dict:
        """Evaluate execution result and return judgment
        
        Args:
            state: Current state
            
        Returns:
            Judgment result with next_action and reason
        """
        next_action = self.route(state)
        
        return {
            "next_action": next_action,
            "reason": self._get_judgment_reason(state, next_action),
            "quality_score": self._calculate_quality_score(state),
        }
    
    def _get_judgment_reason(self, state: AgentState, action: str) -> str:
        """Get reason for judgment decision"""
        if action == "retry":
            return f"Retry attempt {state.get('retry_count', 0) + 1}/{self.MAX_RETRIES}"
        elif action == "human_review":
            return "Maximum retries exceeded or error requires human intervention"
        elif action == "finish":
            return "Task completed successfully"
        return "Continue execution"
    
    def _calculate_quality_score(self, state: AgentState) -> float:
        """Calculate quality score for the result (0-1)"""
        if not state.get("working_memory"):
            return 0.0
        
        # Placeholder for quality evaluation logic
        return 0.8


class LoopRouter(BaseRouter):
    """Loop Router - handles execution loops
    
    Implements the LoopRouter pattern from architecture:
    - Continue: Loop back to agent node
    - Finish: Exit loop to final node
    """
    
    def __init__(self):
        super().__init__()
        self.routes = {
            "continue": "agent_node",
            "finish": "final_node",
        }
    
    def route(self, state: AgentState) -> Literal["agent_node", "final_node"]:
        """Determine if continue looping or finish"""
        next_action = state.get("next_action", "finish")
        return self.routes.get(next_action, "final_node")


class DesignReviewRouter(BaseRouter):
    """Design Review specific router
    
    Handles routing within the design_review capability domain.
    """
    
    def __init__(self):
        super().__init__()
        self.routes = {
            "read_file": "read_file_node",
            "analyze_prototype": "analyze_prototype_node",
            "analyze_prd": "analyze_prd_node",
            "generate_report": "generate_report_node",
        }
    
    def route(self, state: DesignReviewState) -> str:
        """Route based on design review state"""
        # Check for tool calls in last message
        messages = state.get("messages", [])
        if messages:
            last_msg = messages[-1]
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                return "tools"
        
        # Check for image in message
        if state.get("has_image"):
            return "analyze_prototype"
        
        # Check status
        status = state.get("status", "")
        if status == "reviewing":
            return "generate_report"
        
        return "llm"


def create_router(router_type: str) -> BaseRouter:
    """Factory function to create router by type
    
    Args:
        router_type: Type of router to create
        
    Returns:
        Router instance
    """
    routers = {
        "intent": IntentRouter,
        "capability": CapabilityRouter,
        "flow": FlowRouter,
        "judge": JudgeRouter,
        "loop": LoopRouter,
        "design_review": DesignReviewRouter,
    }
    
    router_class = routers.get(router_type)
    if not router_class:
        raise ValueError(f"Unknown router type: {router_type}")
    
    return router_class()


def create_conditional_edges(
    router: BaseRouter,
    node_name: str,
    routes_map: dict[str, str]
) -> Callable[[dict], str]:
    """Create conditional edges function for LangGraph
    
    Args:
        router: Router instance
        node_name: Source node name
        routes_map: Mapping from router output to target nodes
        
    Returns:
        Conditional edges function
    """
    def conditional_edges(state: dict) -> str:
        result = router.route(state)
        return routes_map.get(result, "finish")
    
    return conditional_edges