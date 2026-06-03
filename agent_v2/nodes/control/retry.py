"""Retry Handler Node

Implements retry logic following the architecture document:
- Handle error recovery
- Manage retry count
- Reset state for retry
"""

from typing import Optional, Callable


class RetryHandler:
    """Retry handler for error recovery
    
    Responsibilities:
    1. Manage retry count
    2. Reset error state for retry
    3. Backoff strategies
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        backoff_multiplier: float = 2.0,
        initial_delay: float = 1.0
    ):
        """Initialize retry handler
        
        Args:
            max_retries: Maximum retry attempts
            backoff_multiplier: Backoff multiplier for delays
            initial_delay: Initial delay in seconds
        """
        self.max_retries = max_retries
        self.backoff_multiplier = backoff_multiplier
        self.initial_delay = initial_delay
    
    def should_retry(self, state: dict) -> bool:
        """Check if should retry
        
        Args:
            state: Current state
            
        Returns:
            True if should retry
        """
        retry_count = state.get("retry_count", 0)
        return retry_count < self.max_retries
    
    def get_delay(self, retry_count: int) -> float:
        """Calculate backoff delay
        
        Args:
            retry_count: Current retry count
            
        Returns:
            Delay in seconds
        """
        return self.initial_delay * (self.backoff_multiplier ** retry_count)
    
    def handle_retry(self, state: dict) -> dict:
        """Handle retry logic
        
        Args:
            state: Current state with error
            
        Returns:
            State prepared for retry
        """
        retry_count = state.get("retry_count", 0)
        
        if retry_count >= self.max_retries:
            state["next_action"] = "human_review"
            state["status"] = "waiting_human"
            return state
        
        state["error"] = None
        state["retry_count"] = retry_count + 1
        state["status"] = "executing"
        state["next_action"] = "continue"
        
        state["working_memory"]["retry_delay"] = self.get_delay(retry_count)
        state["working_memory"]["last_error"] = state.get("error")
        
        return state


def create_retry_handler(
    max_retries: int = 3,
    backoff_multiplier: float = 2.0,
    initial_delay: float = 1.0
) -> RetryHandler:
    """Factory function to create retry handler
    
    Args:
        max_retries: Maximum retries
        backoff_multiplier: Backoff multiplier
        initial_delay: Initial delay
        
    Returns:
        RetryHandler instance
    """
    return RetryHandler(
        max_retries=max_retries,
        backoff_multiplier=backoff_multiplier,
        initial_delay=initial_delay
    )


def retry_node(state: dict) -> dict:
    """Standalone retry handler function
    
    Args:
        state: Current state
        
    Returns:
        State prepared for retry
    """
    MAX_RETRIES = 3
    
    retry_count = state.get("retry_count", 0)
    
    if retry_count >= MAX_RETRIES:
        state["next_action"] = "human_review"
        state["status"] = "waiting_human"
    else:
        state["error"] = None
        state["retry_count"] = retry_count + 1
        state["status"] = "executing"
        state["next_action"] = "continue"
    
    return state