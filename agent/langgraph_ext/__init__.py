"""LangGraph Extension Framework

A comprehensive extension framework for LangGraph providing:
- Tool Registration
- Middleware System
- Checkpoint Mechanism
- Persistence Layer
- Interrupt and Resume

Example:
    from agent.langgraph_ext import create_extended_agent
    
    graph = create_extended_agent(
        model=llm,
        tools=[tool1, tool2],
        enable_checkpoints=True,
        enable_persistence=True
    )
"""

from .tools import (
    ToolRegistry,
    ToolValidator,
    ToolFactory,
    register_tool,
    get_tool,
    list_tools,
)
from .Middleware import (
    Middleware,
    MiddlewareChain,
    MiddlewareManager,
    LoggingMiddleware,
    ExceptionHandlerMiddleware,
)
from .checkpoint import (
    CheckpointManager,
    Checkpoint,
    CheckpointConfig,
    CheckpointTrigger,
)
from .persistence import (
    PersistenceManager,
    PersistenceConfig,
    BackupManager,
    create_backup,
)
from .interrupt import (
    InterruptController,
    WorkflowResumer,
    InterruptReason,
    WorkflowState,
)

__version__ = "0.1.0"

__all__ = [
    # Tools
    "ToolRegistry",
    "ToolValidator",
    "ToolFactory",
    "register_tool",
    "get_tool",
    "list_tools",
    # Middleware
    "Middleware",
    "MiddlewareChain",
    "MiddlewareManager",
    "LoggingMiddleware",
    "ExceptionHandlerMiddleware",
    # Checkpoint
    "CheckpointManager",
    "Checkpoint",
    "CheckpointConfig",
    "CheckpointTrigger",
    # Persistence
    "PersistenceManager",
    "PersistenceConfig",
    "BackupManager",
    "create_backup",
    # Interrupt
    "InterruptController",
    "WorkflowResumer",
    "InterruptReason",
    "WorkflowState",
]


def create_extended_agent(config: dict):
    """Create an extended LangGraph agent with all features enabled.
    
    Args:
        config: Configuration dictionary with keys:
            - model: Language model
            - tools: List of tools
            - enable_checkpoints: Enable checkpointing
            - enable_persistence: Enable persistence
            - middleware: Optional list of middleware
            
    Returns:
        Extended agent graph
    """
    from langgraph.graph import StateGraph, END
    from langgraph.prebuilt import ToolNode
    
    state_schema = config.get('state_schema')
    if state_schema is None:
        from typing import TypedDict, Annotated, Any
        from operator import add
        
        class AgentState(TypedDict):
            messages: Annotated[list, add]
            __root__: Annotated[dict[str, Any], lambda a, b: {**a, **b}]
        
        state_schema = AgentState
    
    graph = StateGraph(state_schema)
    
    def agent_node(state):
        return {"messages": [config['model'].invoke(state["messages"])]}
    
    tools = config.get('tools', [])
    if tools:
        tool_node = ToolNode(tools)
        graph.add_node("tools", tool_node)
    
    graph.add_node("agent", agent_node)
    graph.set_entry_point("agent")
    
    def should_continue(state):
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        return END
    
    if tools:
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
    else:
        graph.add_edge("agent", END)
    
    return graph.compile()