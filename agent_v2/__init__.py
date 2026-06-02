"""Agent V2 - Refactored Module

Implements the agent architecture following the architecture document:
- Graph = orchestration (状态迁移)
- Node = business logic (业务逻辑)
- State = source of truth (真相来源)

Architecture pattern:
┌─────────────────────────────────────────┐
│              Graph Layer                │
│  (builder.py, routers.py, state.py)      │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│            Nodes Layer                   │
│  (control/ - context, intent, judge,    │
│             retry, human_review, etc.)   │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│          Agents/Capabilities             │
│  (agents/ - design_review, etc.)        │
│  (capabilities/ - resolver, etc.)       │
└─────────────────────────────────────────┘

Key principles from architecture doc:
1. Graph只负责状态迁移 (State transitions)
2. Node管业务逻辑 (Business logic)
3. State = source of truth (Single source of truth)
4. Router = final authority (Deterministic routing)
5. LLM = decision suggestion (Not control)
6. Capability isolation (能力隔离)
7. Dynamic tool binding (动态工具绑定)
"""

from .graph import (
    AgentState,
    DesignReviewState,
    GraphBuilder,
    DesignReviewGraphBuilder,
    create_base_state,
    update_status,
    IntentRouter,
    CapabilityRouter,
    FlowRouter,
    JudgeRouter,
    create_router,
)

from .nodes import (
    ContextHydrationNode,
    IntentRouterNode,
    JudgeNode,
    RetryHandler,
    HumanReviewNode,
    FlowRouterNode,
    create_context_hydration_node,
    create_intent_router_node,
    create_judge_node,
    create_retry_handler,
    create_human_review_node,
    create_flow_router_node,
    context_hydration_node,
    intent_router_node,
    judge_node,
    retry_node,
    human_review_node,
    flow_router_node,
)

from .agents import (
    DesignReviewState,
    DesignReviewCapability,
    read_file_tool,
    analyze_prototype,
    analyze_prd,
    get_all_tools,
    CapabilityRegistry,
    capability_registry,
)

from .registry import (
    ToolRegistry,
    CapabilityRegistry as CapabilityReg,
    get_global_registry,
    get_global_capability_registry,
    register_tool,
    register_capability,
    SchemaBuilder,
    ToolFactory,
    PermissionLevel,
)

from .capabilities import (
    Capability,
    CapabilityResolver,
    get_capability_resolver,
)


__all__ = [
    # Graph
    "AgentState",
    "DesignReviewState",
    "GraphBuilder",
    "DesignReviewGraphBuilder",
    "create_base_state",
    "update_status",
    "IntentRouter",
    "CapabilityRouter",
    "FlowRouter",
    "JudgeRouter",
    "create_router",
    # Nodes
    "ContextHydrationNode",
    "IntentRouterNode",
    "JudgeNode",
    "RetryHandler",
    "HumanReviewNode",
    "FlowRouterNode",
    "create_context_hydration_node",
    "create_intent_router_node",
    "create_judge_node",
    "create_retry_handler",
    "create_human_review_node",
    "create_flow_router_node",
    "context_hydration_node",
    "intent_router_node",
    "judge_node",
    "retry_node",
    "human_review_node",
    "flow_router_node",
    # Agents
    "DesignReviewCapability",
    "read_file_tool",
    "analyze_prototype",
    "analyze_prd",
    "get_all_tools",
    "CapabilityRegistry",
    "capability_registry",
    # Registry
    "ToolRegistry",
    "get_global_registry",
    "get_global_capability_registry",
    "register_tool",
    "register_capability",
    "SchemaBuilder",
    "ToolFactory",
    "PermissionLevel",
    # Capabilities
    "Capability",
    "CapabilityResolver",
    "get_capability_resolver",
]