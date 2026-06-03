"""Agent State Definitions

Implements the unified state model following the architecture document:
- Graph = orchestration (跳转, 中断, 恢复, 生命周期)
- Node = business logic
- State = source of truth

The state model is the core of the entire system, all nodes only read/write state.
This follows the DIP and decoupling principles.
"""

import operator
from typing import TypedDict, Any, Literal, Optional
from langchain_core.messages import BaseMessage, AnyMessage
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from typing_extensions import Annotated


class AgentStatus(TypedDict):
    """System status following FSM pattern"""
    status: Literal[
        "init",           # 初始化
        "routing",        # 路由中
        "executing",      # 执行中
        "reviewing",      # 审核中
        "waiting_human", # 等待人工
        "finished",      # 完成
        "error"          # 错误
    ]


class AgentCapability(TypedDict):
    """Capability domain tracking"""
    capability: str
    agent_type: Optional[str] = None


class AgentNextAction(TypedDict):
    """Next action tracking for router"""
    next_action: Literal[
        "continue",      # 继续执行
        "retry",         # 重试
        "human_review",  # 人工审核
        "finish",        # 结束
        "tool"           # 调用工具
    ]


class AgentState(TypedDict):
    """Unified Agent State following architecture document pattern
    
    Key principles from architecture doc:
    - State is the single source of truth
    - All nodes only read/write state, not directly call each other
    - Status drives routing, not hardcoded if/else
    
    Fields:
        messages: Conversation history (Annotated for appending)
        user_goal: User's objective
        capability: Current capability domain (coding/research/writing/etc)
        status: Current phase (FSM status)
        next_action: Next action (determined by router)
        working_memory: Intermediate results
        tool_results: Tool execution outputs
        final_response: Final output
        error: Error information
        retry_count: Retry counter
        metadata: Additional metadata
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


class DesignReviewState(AgentState):
    """Design Review specific state extension
    
    Extends AgentState with design review specific fields.
    Follows the pattern: AgentState + domain specific fields.
    """
    has_image: bool = False
    image_paths: list[str] = []
    analysis_result: list[dict] = []
    report: Optional[str] = None
    prd_content: Optional[str] = None


class ContextState(TypedDict):
    """Context Hydration state for checkpoint recovery"""
    thread_id: Optional[str]
    conversation_id: Optional[str]
    checkpoint_id: Optional[str]
    messages: Annotated[list[AnyMessage], operator.add]
    state_snapshot: Optional[str]


class FlowControlState(TypedDict):
    """Flow control state for routing decisions"""
    status: str
    next_action: str
    current_node: str
    retry_count: int
    error: Optional[str]


def create_base_state(
    user_goal: str = "",
    capability: str = "unknown",
    thread_id: Optional[str] = None
) -> dict:
    """Factory function to create base state following architecture pattern
    
    Args:
        user_goal: User's objective
        capability: Capability domain
        thread_id: Optional thread ID for checkpoint
    
    Returns:
        Initial state dictionary
    """
    return {
        "messages": [],
        "user_goal": user_goal,
        "capability": capability,
        "status": "init",
        "next_action": "continue",
        "working_memory": {},
        "tool_results": {},
        "final_response": "",
        "error": None,
        "retry_count": 0,
        "metadata": {"thread_id": thread_id} if thread_id else {}
    }


def update_status(
    state: dict,
    new_status: str,
    new_action: Optional[str] = None
) -> dict:
    """Update state status following FSM pattern
    
    Args:
        state: Current state
        new_status: New status (routing/executing/reviewing/etc)
        new_action: Optional new action
    
    Returns:
        Updated state
    """
    state["status"] = new_status
    if new_action:
        state["next_action"] = new_action
    return state


def create_checkpoint_state(state: dict, node_name: str) -> dict:
    """Create state snapshot for checkpoint
    
    Args:
        state: Current state
        node_name: Current node name
    
    Returns:
        State with checkpoint metadata
    """
    return {
        **state,
        "metadata": {
            **state.get("metadata", {}),
            "last_checkpoint_node": node_name,
            "checkpoint_at": "now"  # Will be replaced with actual timestamp
        }
    }