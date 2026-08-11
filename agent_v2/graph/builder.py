"""Graph Builder Module

Implements the graph construction following the architecture document:
- Graph = orchestration (only handles lifecycle: jump, interrupt, recover, lifecycle)
- Node = business logic
- State = source of truth

Key principles from architecture doc:
1. Graph只负责状态迁移 (State transitions)
2. 不要让graph负责: business logic, tool selection, prompt details, complex judgments
3. Graph is orchestration, nodes are business logic

This module provides the main graph builder class that constructs
LangGraph graphs following the recommended architecture pattern.
"""

from typing import Callable, Optional, Any, Literal, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage

from .state import (
    AgentState,
    DesignReviewState,
    create_base_state,
    update_status,
)
from .routers import (
    IntentRouter,
    CapabilityRouter,
    FlowRouter,
    JudgeRouter,
    create_router,
)


class GraphBuilder:
    """Main graph builder class following architecture pattern
    
    This class constructs LangGraph graphs with proper separation:
    - Graph orchestrates state transitions
    - Nodes handle business logic
    - Routers determine control flow
    
    Usage:
        builder = GraphBuilder(state_type=DesignReviewState)
        builder.add_control_nodes()
        builder.add_agent_nodes(agents)
        builder.add_conditional_edges()
        graph = builder.compile(checkpointer=checkpointer)
    """
    
    def __init__(
        self,
        state_type: type = AgentState,
        name: str = "agent_graph"
    ):
        """Initialize graph builder
        
        Args:
            state_type: State class for the graph
            name: Graph name
        """
        self.state_type = state_type
        self.name = name
        self.graph = StateGraph(state_type)
        self.nodes: dict[str, Callable] = {}
        self.routers: dict[str, Any] = {}
        
    def add_node(self, name: str, node: Callable) -> "GraphBuilder":
        """Add a node to the graph
        
        Args:
            name: Node name
            node: Node function
            
        Returns:
            Self for chaining
        """
        self.graph.add_node(name, node)
        self.nodes[name] = node
        return self
    
    def add_control_node(
        self,
        name: str,
        node: Callable,
        router_type: Optional[str] = None
    ) -> "GraphBuilder":
        """Add a control node with optional router
        
        Args:
            name: Node name
            node: Node function
            router_type: Optional router type for conditional routing
            
        Returns:
            Self for chaining
        """
        self.add_node(name, node)
        if router_type:
            self.routers[name] = create_router(router_type)
        return self
    
    def set_entry_point(self, node: str) -> "GraphBuilder":
        """Set graph entry point
        
        Args:
            node: Node name for entry point
            
        Returns:
            Self for chaining
        """
        self.graph.set_entry_point(node)
        return self
    
    def add_edge(self, from_node: str, to_node: str) -> "GraphBuilder":
        """Add directed edge between nodes
        
        Args:
            from_node: Source node
            to_node: Target node
            
        Returns:
            Self for chaining
        """
        self.graph.add_edge(from_node, to_node)
        return self
    
    def add_conditional_edges(
        self,
        from_node: str,
        router: Any,
        routes_map: dict[str, str]
    ) -> "GraphBuilder":
        """Add conditional edges based on router
        
        Args:
            from_node: Source node
            router: Router instance
            routes_map: Mapping from router output to target nodes
            
        Returns:
            Self for chaining
        """
        def route_func(state: dict) -> str:
            result = router.route(state)
            return routes_map.get(result, END)
        
        self.graph.add_conditional_edges(
            from_node,
            route_func,
            routes_map
        )
        return self
    
    def compile(
        self,
        checkpointer: Optional[Any] = None,
        interrupt_before: Optional[list[str]] = None,
        interrupt_after: Optional[list[str]] = None,
    ):
        """Compile the graph
        
        Args:
            checkpointer: Optional checkpointer for state persistence
            interrupt_before: Nodes to interrupt before
            interrupt_after: Nodes to interrupt after
            
        Returns:
            Compiled graph
        """
        compile_kwargs = {}
        
        if checkpointer:
            compile_kwargs["checkpointer"] = checkpointer
        
        if interrupt_before:
            compile_kwargs["interrupt_before"] = interrupt_before
            
        if interrupt_after:
            compile_kwargs["interrupt_after"] = interrupt_after
        
        return self.graph.compile(**compile_kwargs)


class DesignReviewGraphBuilder(GraphBuilder):
    """Design Review specific graph builder
    
    Constructs the design review graph following the recommended pattern:
    START → IntentRouter → CapabilityRouter → AgentNode → JudgeNode → FlowRouter
    
    Architecture pattern:
    - Context Hydration (restore from checkpoint)
    - Intent Router (classify capability)
    - Capability Router (select agent)
    - Agent Node (business logic)
    - Judge Node (quality check)
    - Flow Router (control flow)
    """
    
    def __init__(self):
        super().__init__(state_type=DesignReviewState, name="design_review")
        self._init_routers()
    
    def _init_routers(self):
        """Initialize routers"""
        self.routers = {
            "intent": IntentRouter(),
            "capability": CapabilityRouter(),
            "flow": FlowRouter(),
            "judge": JudgeRouter(),
        }
    
    def build(
        self,
        llm,
        tools: list,
        agent_nodes: dict[str, Callable],
        checkpointer: Optional[Any] = None
    ) -> Any:
        """Build the complete design review graph
        
        Args:
            llm: LLM instance
            tools: List of tools
            agent_nodes: Dict of agent node functions
            checkpointer: Optional checkpointer
            
        Returns:
            Compiled graph
        """
        self._add_context_hydration()
        self._add_intent_router()
        self._add_capability_router()
        self._add_agent_nodes(agent_nodes)
        self._add_judge_node()
        self._add_flow_router()
        self._add_tools(tools)
        self._add_llm_node(llm, tools)
        self._set_edges()
        
        return self.compile(checkpointer=checkpointer)
    
    def _add_context_hydration(self):
        """Add context hydration node for checkpoint recovery"""
        def context_hydration(state: DesignReviewState) -> dict:
            thread_id = state.get("metadata", {}).get("thread_id")
            if thread_id:
                state["status"] = "routing"
            return state
        
        self.add_node("context_hydration", context_hydration)
    
    def _add_intent_router(self):
        """Add intent router node"""
        def intent_router(state: DesignReviewState) -> dict:
            router = self.routers["intent"]
            result = router.route(state)
            
            state["capability"] = result.replace("_agent", "") if result else "unknown"
            state["status"] = "routing"
            
            return update_status(state, "routing")
        
        self.add_control_node("intent_router", intent_router, "intent")
    
    def _add_capability_router(self):
        """Add capability router node"""
        def capability_router(state: DesignReviewState) -> dict:
            capability = state.get("capability", "")
            
            if capability == "design_review":
                state["status"] = "executing"
                return update_status(state, "executing")
            
            return state
        
        self.add_control_node("capability_router", capability_router, "capability")
    
    def _add_agent_nodes(self, agent_nodes: dict[str, Callable]):
        """Add agent nodes"""
        for name, node in agent_nodes.items():
            self.add_node(name, node)
    
    def _add_judge_node(self):
        """Add judge node for quality evaluation"""
        def judge_node(state: DesignReviewState) -> dict:
            router = self.routers["judge"]
            judgment = router.evaluate_result(state)
            
            state["next_action"] = judgment["next_action"]
            
            if judgment["next_action"] == "retry":
                state["retry_count"] = state.get("retry_count", 0) + 1
            elif judgment["next_action"] == "human_review":
                state["status"] = "waiting_human"
            
            return state
        
        self.add_control_node("judge_node", judge_node, "judge")
    
    def _add_flow_router(self):
        """Add flow router node"""
        def flow_router(state: DesignReviewState) -> dict:
            router = self.routers["flow"]
            result = router.route(state)
            
            return state
        
        self.add_control_node("flow_router", flow_router, "flow")
    
    def _add_tools(self, tools: list):
        """Add tool node"""
        if tools:
            tool_node = ToolNode(tools)
            self.add_node("tools", tool_node)
    
    def _add_llm_node(self, llm, tools: list):
        """Add LLM node with tool binding"""
        def llm_node(state: DesignReviewState) -> dict:
            llm_with_tools = llm.bind_tools(tools)
            result = llm_with_tools.invoke(state["messages"])
            state["messages"] = state.get("messages", []) + [result]
            state["llm_calls"] = state.get("llm_calls", 0) + 1
            return state
        
        self.add_node("llm", llm_node)
    
    def _set_edges(self):
        """Set graph edges"""
        self.set_entry_point("context_hydration")
        self.add_edge("context_hydration", "intent_router")
        
        self.graph.add_conditional_edges(
            "intent_router",
            lambda s: s.get("capability", "unknown"),
            {
                "design_review": "capability_router",
                "unknown_capability": END,
            }
        )
        
        self.add_edge("capability_router", "llm")
        
        self.graph.add_conditional_edges(
            "llm",
            lambda s: self._should_continue(s),
            {
                "tools": "tools",
                "agent": "judge_node",
                "end": END,
            }
        )
        
        self.add_edge("tools", "llm")
        self.add_edge("judge_node", "flow_router")
        
        self.graph.add_conditional_edges(
            "flow_router",
            lambda s: s.get("next_action", "finish"),
            {
                "continue": "llm",
                "retry": "llm",
                "human_review": END,
                "finish": END,
            }
        )
    
    def _should_continue(self, state: DesignReviewState) -> str:
        """Determine if graph should continue"""
        messages = state.get("messages", [])
        if not messages:
            return "end"
        
        last_msg = messages[-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        
        return "agent"


def create_graph(
    state_type: type = AgentState,
    name: str = "agent"
) -> GraphBuilder:
    """Factory function to create graph builder
    
    Args:
        state_type: State class
        name: Graph name
        
    Returns:
        GraphBuilder instance
    """
    return GraphBuilder(state_type=state_type, name=name)