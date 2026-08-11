"""Context Hydration Node

Implements Context Hydration following the architecture document:
- Restore context from checkpoint
- Restore memory
- Initialize state for new requests

This is the first node in the pipeline, responsible for preparing
the state before any processing occurs.
"""

from typing import Optional, Any, TypedDict
from langchain_core.messages import AnyMessage
from typing_extensions import Annotated


class ContextState(TypedDict):
    """State for context hydration"""
    thread_id: Optional[str]
    conversation_id: Optional[str]
    checkpoint_id: Optional[str]
    messages: Annotated[list[AnyMessage], lambda a, b: a + b]


class ContextHydrationNode:
    """Context hydration node for checkpoint recovery
    
    Responsibilities:
    1. Restore state from checkpoint if thread_id provided
    2. Initialize fresh state for new requests
    3. Setup conversation context
    """
    
    def __init__(self, checkpointer: Optional[Any] = None):
        """Initialize context hydration node
        
        Args:
            checkpointer: Optional checkpointer for state recovery
        """
        self.checkpointer = checkpointer
    
    def __call__(self, state: dict) -> dict:
        """Execute context hydration
        
        Args:
            state: Current state
            
        Returns:
            Hydrated state
        """
        return self.hydrate(state)
    
    def hydrate(self, state: dict) -> dict:
        """Hydrate context from checkpoint or create fresh
        
        Args:
            state: Current state with thread_id/conversation_id
            
        Returns:
            Hydrated state
        """
        thread_id = state.get("metadata", {}).get("thread_id")
        conversation_id = state.get("metadata", {}).get("conversation_id")
        
        if thread_id and self.checkpointer:
            checkpoint_data = self._load_checkpoint(thread_id)
            if checkpoint_data:
                state = self._restore_from_checkpoint(state, checkpoint_data)
        
        if "messages" not in state:
            state["messages"] = []
        
        if "metadata" not in state:
            state["metadata"] = {}
        
        state["metadata"]["hydrated"] = True
        
        return state
    
    def _load_checkpoint(self, thread_id: str) -> Optional[dict]:
        """Load checkpoint from storage
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            Checkpoint data or None
        """
        if not self.checkpointer:
            return None
        
        try:
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint = self.checkpointer.get(config)
            return checkpoint
        except Exception:
            return None
    
    def _restore_from_checkpoint(self, state: dict, checkpoint_data: dict) -> dict:
        """Restore state from checkpoint data
        
        Args:
            state: Current state
            checkpoint_data: Checkpoint data
            
        Returns:
            Restored state
        """
        if checkpoint_data:
            checkpoint_values = checkpoint_data.get("values", {})
            
            if "messages" in checkpoint_values:
                state["messages"] = checkpoint_values["messages"]
            
            if "status" in checkpoint_values:
                state["status"] = checkpoint_values["status"]
            
            state["checkpoint_restored"] = True
        
        return state


def create_context_hydration_node(
    checkpointer: Optional[Any] = None
) -> ContextHydrationNode:
    """Factory function to create context hydration node
    
    Args:
        checkpointer: Optional checkpointer
        
    Returns:
        ContextHydrationNode instance
    """
    return ContextHydrationNode(checkpointer=checkpointer)


def context_hydration_node(state: dict) -> dict:
    """Standalone context hydration function
    
    For use without class instantiation.
    
    Args:
        state: Current state
        
    Returns:
        Hydrated state
    """
    if "messages" not in state:
        state["messages"] = []
    
    if "metadata" not in state:
        state["metadata"] = {}
    
    state["metadata"]["hydrated"] = True
    state["status"] = "init"
    
    return state