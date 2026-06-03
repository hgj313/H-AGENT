"""Human Review Node

Implements Human-in-the-loop (HITL) following the architecture document:
- Interrupt workflow for human approval
- Handle high-risk operations
- Support checkpoint recovery

LangGraph provides interrupt() for this pattern.
"""

from typing import Optional, Any, TypedDict


class HumanReviewRequest(TypedDict):
    """Human review request structure"""
    reason: str
    message: str
    options: list[str]
    default_action: str


class HumanReviewNode:
    """Human review node for human-in-the-loop
    
    Responsibilities:
    1. Interrupt workflow for human approval
    2. Present decision options to human
    3. Resume workflow based on human decision
    
    High-risk operations that should trigger human review:
    - Delete operations
    - Email/notification sending
    - Shell command execution
    - Payment transactions
    - Data export
    """
    
    def __init__(self, interrupt_func: Optional[Any] = None):
        """Initialize human review node
        
        Args:
            interrupt_func: Optional custom interrupt function
        """
        self.interrupt_func = interrupt_func or self._default_interrupt
    
    def __call__(self, state: dict) -> dict:
        """Execute human review
        
        Args:
            state: Current state
            
        Returns:
            State with review result
        """
        return self.review(state)
    
    def review(self, state: dict) -> dict:
        """Request human review
        
        Args:
            state: State with metadata about what's being reviewed
            
        Returns:
            State with review decision
        """
        reason = state.get("error") or "Manual review required"
        message = self._create_review_message(state)
        
        request = HumanReviewRequest(
            reason=reason,
            message=message,
            options=["approve", "reject", "modify"],
            default_action="reject"
        )
        
        state["metadata"]["human_review_request"] = request
        
        state["next_action"] = "human_review"
        state["status"] = "waiting_human"
        
        return state
    
    def _create_review_message(self, state: dict) -> str:
        """Create human review message
        
        Args:
            state: Current state
            
        Returns:
            Review message
        """
        error = state.get("error", "Unknown error")
        retry_count = state.get("retry_count", 0)
        
        return (
            f"Human review required for the following:\n"
            f"- Error: {error}\n"
            f"- Retry count: {retry_count}\n"
            f"- Last operation: {state.get('working_memory', {}).get('last_operation', 'unknown')}"
        )
    
    def _default_interrupt(self, data: dict) -> Any:
        """Default interrupt function using LangGraph interrupt
        
        Args:
            data: Interrupt data
            
        Returns:
            Interrupt result
        """
        try:
            from langgraph.types import interrupt
            return interrupt(data)
        except ImportError:
            return {"approved": False, "message": "Interrupt not available"}


def create_human_review_node(
    interrupt_func: Optional[Any] = None
) -> HumanReviewNode:
    """Factory function to create human review node
    
    Args:
        interrupt_func: Optional custom interrupt
        
    Returns:
        HumanReviewNode instance
    """
    return HumanReviewNode(interrupt_func=interrupt_func)


def human_review_node(state: dict) -> dict:
    """Standalone human review function
    
    Args:
        state: Current state
        
    Returns:
        State with human_review status
    """
    state["status"] = "waiting_human"
    state["next_action"] = "human_review"
    
    state["metadata"]["human_review_required"] = True
    state["metadata"]["review_reason"] = state.get("error", "Manual review needed")
    
    return state