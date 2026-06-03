"""Result Judge Node

Implements Result Judge following the architecture document:
- Evaluate execution quality
- Determine whether to continue, retry, request human review, or finish
- Core component for quality control

This is a key pattern from the architecture: Result Judge → Flow Router
"""

from typing import Literal, Optional, TypedDict


class JudgeResult(TypedDict):
    """Judge result structure"""
    next_action: str
    quality_score: float
    reason: str
    can_retry: bool
    needs_human_review: bool


class JudgeNode:
    """Judge node for execution quality evaluation
    
    Responsibilities:
    1. Evaluate execution results
    2. Check for errors
    3. Determine next action (continue/retry/human_review/finish)
    
    Architecture pattern:
    ┌──────────────┐
    │   Agent      │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Judge      │  ← This node
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Router    │
    └─────────────┘
    """
    
    MAX_RETRIES: int = 3
    
    def __init__(self, max_retries: int = 3):
        """Initialize judge node
        
        Args:
            max_retries: Maximum retry attempts
        """
        self.MAX_RETRIES = max_retries
    
    def __call__(self, state: dict) -> dict:
        """Execute judgment
        
        Args:
            state: Current state with working_memory, tool_results, error
            
        Returns:
            State with next_action set
        """
        return self.judge(state)
    
    def judge(self, state: dict) -> dict:
        """Judge execution and determine next action
        
        Args:
            state: Current state
            
        Returns:
            State with next_action, status updated
        """
        result = self.evaluate(state)
        
        state["next_action"] = result["next_action"]
        state["metadata"]["judge_result"] = result
        
        if result["next_action"] == "retry":
            state["retry_count"] = state.get("retry_count", 0) + 1
            state["status"] = "executing"
        elif result["next_action"] == "human_review":
            state["status"] = "waiting_human"
        elif result["next_action"] == "finish":
            state["status"] = "finished"
        
        return state
    
    def evaluate(self, state: dict) -> JudgeResult:
        """Evaluate execution result
        
        Args:
            state: Current state
            
        Returns:
            JudgeResult with decision
        """
        error = state.get("error")
        retry_count = state.get("retry_count", 0)
        
        if error:
            if retry_count < self.MAX_RETRIES:
                return JudgeResult(
                    next_action="retry",
                    quality_score=0.0,
                    reason=f"Error occurred: {error}. Retry {retry_count + 1}/{self.MAX_RETRIES}",
                    can_retry=True,
                    needs_human_review=False
                )
            else:
                return JudgeResult(
                    next_action="human_review",
                    quality_score=0.0,
                    reason="Maximum retries exceeded",
                    can_retry=False,
                    needs_human_review=True
                )
        
        final_response = state.get("final_response")
        if final_response:
            return JudgeResult(
                next_action="finish",
                quality_score=self._calculate_quality(state),
                reason="Task completed successfully",
                can_retry=False,
                needs_human_review=False
            )
        
        working_memory = state.get("working_memory", {})
        if working_memory.get("needs_continuation"):
            return JudgeResult(
                next_action="continue",
                quality_score=self._calculate_quality(state),
                reason="More work needed",
                can_retry=False,
                needs_human_review=False
            )
        
        return JudgeResult(
            next_action="continue",
            quality_score=self._calculate_quality(state),
            reason="Continue execution",
            can_retry=False,
            needs_human_review=False
        )
    
    def _calculate_quality(self, state: dict) -> float:
        """Calculate quality score (0-1)
        
        Args:
            state: Current state
            
        Returns:
            Quality score
        """
        tool_results = state.get("tool_results", {})
        
        if not tool_results:
            return 0.5
        
        success_count = sum(
            1 for r in tool_results.values()
            if isinstance(r, dict) and r.get("success")
        )
        total_count = len(tool_results)
        
        if total_count == 0:
            return 0.5
        
        return success_count / total_count


def create_judge_node(max_retries: int = 3) -> JudgeNode:
    """Factory function to create judge node
    
    Args:
        max_retries: Maximum retry attempts
        
    Returns:
        JudgeNode instance
    """
    return JudgeNode(max_retries=max_retries)


def judge_node(state: dict) -> dict:
    """Standalone judge function
    
    Args:
        state: Current state
        
    Returns:
        State with next_action set
    """
    MAX_RETRIES = 3
    
    error = state.get("error")
    retry_count = state.get("retry_count", 0)
    
    if error:
        if retry_count < MAX_RETRIES:
            state["next_action"] = "retry"
            state["retry_count"] = retry_count + 1
            state["status"] = "executing"
        else:
            state["next_action"] = "human_review"
            state["status"] = "waiting_human"
    elif state.get("final_response"):
        state["next_action"] = "finish"
        state["status"] = "finished"
    else:
        state["next_action"] = "continue"
    
    return state