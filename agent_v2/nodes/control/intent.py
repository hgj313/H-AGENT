"""Intent Router Node

Implements Intent Router following the architecture document:
- Classify user intent to capability domain
- First router in the pipeline
- Deterministic routing based on state
"""

from typing import Literal, Optional, Any
from langchain_core.messages import HumanMessage


class IntentRouterNode:
    """Intent router node for capability classification
    
    Responsibilities:
    1. Analyze user input
    2. Classify intent to capability domain
    3. Update state with capability
    
    Supported capabilities:
    - coding: Code generation, review, modification
    - research: Information retrieval, analysis
    - writing: Content creation, editing
    - design_review: Design document review
    - analytics: Data analysis, visualization
    """
    
    CAPABILITY_KEYWORDS = {
        "coding": [
            "code", "implement", "function", "class", "debug",
            "refactor", "test", "python", "javascript", "api",
            "module", "script", "algorithm", "data structure"
        ],
        "research": [
            "search", "find", "research", "information", "lookup",
            "query", "retrieve", "analyze", "investigate", "explore"
        ],
        "writing": [
            "write", "create", "compose", "draft", "edit",
            "document", "content", "article", "report", "summary"
        ],
        "design_review": [
            "review", "design", "prototype", "prd", "specification",
            "architecture", "ui", "ux", "mockup", "wireframe"
        ],
        "analytics": [
            "analyze", "chart", "graph", "visualization", "data",
            "metrics", "statistics", "dashboard", "report", "insights"
        ],
    }
    
    def __init__(self, llm: Optional[Any] = None):
        """Initialize intent router
        
        Args:
            llm: Optional LLM for advanced intent detection
        """
        self.llm = llm
    
    def __call__(self, state: dict) -> dict:
        """Execute intent routing
        
        Args:
            state: Current state with messages/user_goal
            
        Returns:
            State with capability set
        """
        return self.route(state)
    
    def route(self, state: dict) -> dict:
        """Route based on user input
        
        Args:
            state: State with user_goal or last message
            
        Returns:
            State with capability set
        """
        user_goal = state.get("user_goal", "")
        
        if not user_goal:
            messages = state.get("messages", [])
            if messages and isinstance(messages[-1], HumanMessage):
                user_goal = messages[-1].content
        
        capability = self._classify_intent(user_goal)
        
        state["capability"] = capability
        state["status"] = "routing"
        
        return state
    
    def _classify_intent(self, text: str) -> str:
        """Classify intent from text
        
        Args:
            text: User input text
            
        Returns:
            Capability domain
        """
        if not text:
            return "unknown"
        
        text_lower = text.lower()
        scores = {}
        
        for capability, keywords in self.CAPABILITY_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword in text_lower)
            scores[capability] = score
        
        if not scores or max(scores.values()) == 0:
            return "general"
        
        return max(scores, key=scores.get)


def create_intent_router_node(
    llm: Optional[Any] = None
) -> IntentRouterNode:
    """Factory function to create intent router node
    
    Args:
        llm: Optional LLM
        
    Returns:
        IntentRouterNode instance
    """
    return IntentRouterNode(llm=llm)


def intent_router_node(state: dict) -> dict:
    """Standalone intent routing function
    
    Simple keyword-based intent detection.
    
    Args:
        state: Current state
        
    Returns:
        State with capability
    """
    user_goal = state.get("user_goal", "")
    
    if not user_goal:
        return state
    
    text_lower = user_goal.lower()
    
    if any(k in text_lower for k in ["code", "implement", "function"]):
        capability = "coding"
    elif any(k in text_lower for k in ["search", "find", "research"]):
        capability = "research"
    elif any(k in text_lower for k in ["write", "create", "draft"]):
        capability = "writing"
    elif any(k in text_lower for k in ["review", "design", "prototype"]):
        capability = "design_review"
    elif any(k in text_lower for k in ["analyze", "chart", "graph"]):
        capability = "analytics"
    else:
        capability = "general"
    
    state["capability"] = capability
    state["status"] = "routing"
    
    return state