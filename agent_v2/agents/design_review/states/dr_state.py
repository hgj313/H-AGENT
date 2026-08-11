"""Design Review State Definition

Extends AgentState with design review specific fields.
Following the architecture: State = source of truth

Design review capability specific state fields:
- has_image: Whether current request contains images
- image_paths: Image file paths
- analysis_result: Prototype analysis results
- report: Generated review report
- prd_content: PRD document content
"""

import operator
from typing import TypedDict, Any, Optional, Annotated
from langchain_core.messages import AnyMessage


class DesignReviewState(TypedDict):
    """Design Review capability specific state
    
    Extends base AgentState with:
    - Image handling for prototype review
    - Analysis result storage
    - Report generation
    
    Architecture pattern:
    AgentState + domain_specific_fields = CapabilityState
    """
    messages: Annotated[list[AnyMessage], operator.add]
    user_goal: str
    capability: str
    status: str
    next_action: str
    working_memory: dict[str, Any]
    tool_results: dict[str, Any]
    final_response: str
    error: Optional[str]
    retry_count: int
    metadata: dict[str, Any]
    
    has_image: bool
    image_paths: list[str]
    analysis_result: list[dict]
    report: Optional[str]
    prd_content: Optional[str]
    llm_calls: int


def create_design_review_state(
    user_goal: str = "",
    thread_id: Optional[str] = None,
    has_image: bool = False,
    image_paths: list[str] = None
) -> dict:
    """Factory function to create design review state
    
    Args:
        user_goal: User's review objective
        thread_id: Optional thread ID for checkpoint
        has_image: Whether request has images
        image_paths: List of image paths
        
    Returns:
        Initial design review state
    """
    return {
        "messages": [],
        "user_goal": user_goal,
        "capability": "design_review",
        "status": "init",
        "next_action": "continue",
        "working_memory": {},
        "tool_results": {},
        "final_response": "",
        "error": None,
        "retry_count": 0,
        "metadata": {"thread_id": thread_id} if thread_id else {},
        "has_image": has_image,
        "image_paths": image_paths or [],
        "analysis_result": [],
        "report": None,
        "prd_content": None,
        "llm_calls": 0,
    }


def detect_image_in_message(last_msg) -> tuple[bool, list[str]]:
    """Detect images in message content
    
    Args:
        last_msg: Last message with content
        
    Returns:
        Tuple of (has_image, image_urls)
    """
    from langchain_core.messages import HumanMessage
    
    if not isinstance(last_msg, HumanMessage):
        return False, []
    
    content = last_msg.content
    image_urls = []
    
    if isinstance(content, str):
        return False, []
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "image_url":
                    image_url = item.get("image_url", {})
                    if isinstance(image_url, dict):
                        url = image_url.get("url", "")
                    elif isinstance(image_url, str):
                        url = image_url
                    else:
                        continue
                    if url:
                        image_urls.append(url)
                elif item.get("type") == "image" and item.get("source") == "base64":
                    pass
    
    return len(image_urls) > 0, image_urls