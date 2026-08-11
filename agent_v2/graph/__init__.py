"""Graph Module

Implements the graph layer following the architecture document:
- Graph = orchestration (状态迁移)
- Node = business logic
- State = source of truth

This module exports the main graph components:
- state: State definitions and utilities
- routers: Routing logic
- builder: Graph construction utilities
"""

from .state import (
    AgentState,
    DesignReviewState,
    AgentStatus,
    AgentCapability,
    AgentNextAction,
    create_base_state,
    update_status,
    create_checkpoint_state,
)

from .routers import (
    BaseRouter,
    IntentRouter,
    CapabilityRouter,
    FlowRouter,
    JudgeRouter,
    LoopRouter,
    DesignReviewRouter,
    create_router,
    create_conditional_edges,
)

from .builder import (
    GraphBuilder,
    DesignReviewGraphBuilder,
    create_graph,
)

__all__ = [
    # State
    "AgentState",
    "DesignReviewState",
    "AgentStatus",
    "AgentCapability",
    "AgentNextAction",
    "create_base_state",
    "update_status",
    "create_checkpoint_state",
    # Routers
    "BaseRouter",
    "IntentRouter",
    "CapabilityRouter",
    "FlowRouter",
    "JudgeRouter",
    "LoopRouter",
    "DesignReviewRouter",
    "create_router",
    "create_conditional_edges",
    # Builder
    "GraphBuilder",
    "DesignReviewGraphBuilder",
    "create_graph",
]