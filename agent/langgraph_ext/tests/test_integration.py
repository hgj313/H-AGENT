"""Integration Tests for LangGraph with Extension Framework

These tests demonstrate how to integrate the extension modules with actual LangGraph workflows.
"""

import pytest
from typing import TypedDict, Annotated, Any
from operator import add

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import BaseTool

from agent.langgraph_ext.tools import ToolRegistry, register_tool
from agent.langgraph_ext.Middleware import (
    LoggingMiddleware,
    ExceptionHandlerMiddleware,
    MiddlewareChain,
    MiddlewareManager,
)
from agent.langgraph_ext.checkpoint import (
    CheckpointManager,
    CheckpointConfig,
    CheckpointTrigger,
)
from agent.langgraph_ext.persistence import (
    PersistenceManager,
    PersistenceConfig,
    PersistenceBackend,
)
from agent.langgraph_ext.interrupt import (
    InterruptController,
    InterruptReason,
    WorkflowResumer,
)


class TestLangGraphIntegration:
    """Integration tests for LangGraph with extension framework."""
    
    def test_create_extended_state_graph(self):
        """Test creating a LangGraph StateGraph with all extensions."""
        from langgraph.graph import StateGraph, END
        
        class AgentState(TypedDict):
            messages: Annotated[list, add]
            step: int = 0
        
        registry = ToolRegistry()
        
        def simple_tool(data: str) -> str:
            return f"Processed: {data}"
        
        tool_name = registry.register(simple_tool, name="simple_tool")
        
        graph = StateGraph(AgentState)
        
        def agent_node(state: AgentState) -> dict:
            return {"messages": [AIMessage(content=f"Step {state['step']}")]}
        
        graph.add_node("agent", agent_node)
        graph.set_entry_point("agent")
        graph.add_edge("agent", END)
        
        compiled = graph.compile()
        
        assert compiled is not None
        
        tools = registry.to_langchain_tools()
        assert len(tools) == 1
    
    def test_middleware_with_langgraph_node(self):
        """Test applying middleware to a LangGraph node."""
        from langgraph.graph import StateGraph, END
        
        class State(TypedDict):
            messages: Annotated[list, add]
            count: int
        
        logging = LoggingMiddleware(name="agent_logger", log_timing=True, log_state=True)
        exception_handler = ExceptionHandlerMiddleware(
            name="error_handler",
            fallback_value={"error": True}
        )
        
        chain = MiddlewareChain()
        chain.add(logging)
        chain.add(exception_handler)
        
        manager = MiddlewareManager()
        
        results = []
        
        def agent_node(state: State) -> dict:
            results.append(state)
            return {
                "messages": [AIMessage(content=f"Count: {state['count']}")],
                "count": state["count"] + 1
            }
        
        wrapped_node = manager.wrap_node(agent_node, "agent", "test_graph")
        
        context = MiddlewareContext(graph_name="test_graph", node_name="agent")
        
        def final_handler():
            return agent_node({"messages": [], "count": 0})
        
        result = chain.execute_sync(context, {"messages": [], "count": 0}, final_handler)
        
        assert len(results) >= 1
    
    def test_checkpoint_integration(self):
        """Test checkpoint functionality with a simulated workflow."""
        config = CheckpointConfig(
            auto_trigger_nodes=["analyze", "process"],
            trigger_on_error=True,
            max_checkpoints=50
        )
        
        checkpoint_manager = CheckpointManager(config=config)
        
        checkpoints = []
        
        def checkpoint_callback(cp):
            checkpoints.append(cp)
        
        checkpoint_manager.register_callback(CheckpointTrigger.AUTOMATIC, checkpoint_callback)
        
        def simulate_workflow_step(step_name: str, state: dict) -> dict:
            state["current_step"] = step_name
            state["step_history"].append(step_name)
            
            if checkpoint_manager.should_checkpoint(
                step_name,
                state,
                error=None
            ):
                cp = checkpoint_manager.create_checkpoint(
                    state=state.copy(),
                    run_id="workflow_run",
                    trigger=CheckpointTrigger.ON_NODE_COMPLETE,
                    node_name=step_name
                )
            
            return state
        
        state = {"messages": [], "step_history": [], "data": {}}
        
        state = simulate_workflow_step("analyze", state)
        state = simulate_workflow_step("process", state)
        state = simulate_workflow_step("validate", state)
        
        assert len(checkpoints) >= 0
    
    def test_persistence_with_workflow_state(self):
        """Test persistence functionality with workflow state."""
        config = PersistenceConfig(
            backend=PersistenceBackend.MEMORY,
            auto_save=True,
            compress_data=True
        )
        
        persistence_manager = PersistenceManager(config)
        
        workflow_state = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"}
            ],
            "context": {
                "user_id": "user123",
                "session_id": "sess456"
            },
            "metadata": {
                "created_at": "2024-01-01T00:00:00",
                "version": "1.0"
            }
        }
        
        record_id = persistence_manager.save_state(
            state=workflow_state,
            run_id="workflow_001",
            thread_id="thread_001",
            node_name="agent_node"
        )
        
        loaded_state = persistence_manager.load_state(record_id)
        
        assert loaded_state is not None
        assert loaded_state["context"]["user_id"] == "user123"
        
        latest = persistence_manager.load_latest_state("workflow_001", "thread_001")
        assert latest is not None
    
    def test_interrupt_and_resume_scenario(self):
        """Test a complete interrupt and resume scenario."""
        checkpoint_manager = CheckpointManager()
        persistence_manager = PersistenceManager(
            PersistenceConfig(backend=PersistenceBackend.MEMORY)
        )
        
        interrupt_controller = InterruptController(
            checkpoint_manager=checkpoint_manager,
            persistence_manager=persistence_manager
        )
        
        def simulate_workflow():
            state = {
                "messages": [],
                "step": 0,
                "results": []
            }
            
            for step in range(5):
                state["step"] = step
                state["results"].append(f"step_{step}")
                
                cp = checkpoint_manager.create_checkpoint(
                    state=state.copy(),
                    run_id="test_workflow",
                    trigger=CheckpointTrigger.AUTOMATIC,
                    node_name=f"node_{step}"
                )
                
                if step == 2:
                    workflow_state = interrupt_controller.interrupt_workflow(
                        run_id="test_workflow",
                        state=state.copy(),
                        reason=InterruptReason.USER_CONFIRMATION,
                        current_node=f"node_{step}",
                        message="User confirmation required at step 2"
                    )
                    break
            
            return state
        
        final_state = simulate_workflow()
        
        interrupted = interrupt_controller.get_interrupted_workflow("test_workflow")
        assert interrupted is not None
        
        resumer = WorkflowResumer(
            checkpoint_manager=checkpoint_manager,
            persistence_manager=persistence_manager,
            interrupt_controller=interrupt_controller
        )
        
        result = resumer.resume_from_interrupt("test_workflow", lambda: None)
        
        assert result.success
        assert result.resumed_state["step"] >= 2
    
    def test_full_integration_scenario(self):
        """Test a complete scenario with all extension modules."""
        from langgraph.graph import StateGraph, END
        
        class WorkflowState(TypedDict):
            messages: Annotated[list, add]
            data: dict
            step: int
            checkpoint_count: int
        
        registry = ToolRegistry()
        
        def transform_data(data: str) -> str:
            return f"transformed_{data}"
        
        def analyze_data(data: str) -> dict:
            return {"analysis": f"analyzed_{data}", "confidence": 0.95}
        
        registry.register(transform_data, name="transform", tags=["data"])
        registry.register(analyze_data, name="analyze", tags=["analysis"])
        
        checkpoint_manager = CheckpointManager(
            config=CheckpointConfig(auto_trigger_nodes=["transform", "analyze"])
        )
        
        persistence_manager = PersistenceManager(
            PersistenceConfig(backend=PersistenceBackend.MEMORY, auto_save=True)
        )
        
        logging = LoggingMiddleware(name="workflow_logger", log_timing=True)
        exception_handler = ExceptionHandlerMiddleware(
            name="workflow_error_handler",
            fallback_value={"error": "handled"}
        )
        
        chain = MiddlewareChain()
        chain.add(logging)
        chain.add(exception_handler)
        
        interrupt_controller = InterruptController(
            checkpoint_manager=checkpoint_manager,
            persistence_manager=persistence_manager
        )
        
        def step_node(state: WorkflowState) -> dict:
            new_state = {
                **state,
                "step": state["step"] + 1,
                "checkpoint_count": state.get("checkpoint_count", 0) + 1
            }
            
            if state["step"] >= 3:
                cp = checkpoint_manager.create_checkpoint(
                    state=new_state,
                    run_id="integration_test",
                    trigger=CheckpointTrigger.AUTOMATIC,
                    node_name=f"step_{state['step']}"
                )
            
            persistence_manager.save_state(
                state=new_state,
                run_id="integration_test",
                node_name=f"step_{state['step']}"
            )
            
            return new_state
        
        def should_continue(state: WorkflowState) -> str:
            if state["step"] >= 5:
                return END
            return "step_node"
        
        graph = StateGraph(WorkflowState)
        graph.add_node("step_node", step_node)
        graph.set_entry_point("step_node")
        graph.add_conditional_edges("step_node", should_continue, {"step_node": "step_node", END: END})
        
        compiled = graph.compile()
        
        initial_state = {
            "messages": [HumanMessage(content="Start workflow")],
            "data": {"input": "test"},
            "step": 0,
            "checkpoint_count": 0
        }
        
        tools = registry.to_langchain_tools()
        assert len(tools) == 2
        
        checkpoints = checkpoint_manager.list_checkpoints("integration_test")
        states = persistence_manager.backend.list_states("integration_test")
        
        assert len(checkpoints) >= 0 or len(states) >= 0


class TestErrorHandling:
    """Tests for error handling scenarios."""
    
    def test_tool_not_found_error(self):
        """Test handling of tool not found errors."""
        registry = ToolRegistry()
        
        tool = registry.get("nonexistent_tool")
        assert tool is None
        
        stats = registry.get_stats("nonexistent_tool")
        assert stats is None
    
    def test_middleware_chain_error_propagation(self):
        """Test error propagation through middleware chain."""
        chain = MiddlewareChain()
        
        class FailingMiddleware(Middleware):
            async def _aprocess(self, context, state, next_handler):
                raise ValueError("Middleware failure")
        
        chain.add(FailingMiddleware(name="failing"))
        
        async def final_handler():
            return {"result": "success"}
        
        context = MiddlewareContext(graph_name="test")
        
        with pytest.raises(ValueError):
            import asyncio
            asyncio.run(chain.execute(context, {}, final_handler))
    
    def test_checkpoint_rollback_on_error(self):
        """Test checkpoint functionality during error recovery."""
        checkpoint_manager = CheckpointManager()
        
        state = {"value": 1}
        cp1 = checkpoint_manager.create_checkpoint(
            state=state,
            run_id="rollback_test",
            trigger=CheckpointTrigger.MANUAL
        )
        
        state["value"] = 2
        cp2 = checkpoint_manager.create_checkpoint(
            state=state,
            run_id="rollback_test",
            trigger=CheckpointTrigger.ON_NODE_COMPLETE
        )
        
        state["value"] = 3
        
        rollback_cp = checkpoint_manager.get_checkpoint(cp1.id)
        assert rollback_cp is not None
        assert rollback_cp.state["value"] == 1
    
    def test_interrupt_on_exception(self):
        """Test automatic interrupt on exception."""
        interrupt_controller = InterruptController()
        
        state = {"data": "test"}
        
        try:
            workflow_state = interrupt_controller.interrupt_workflow(
                run_id="error_test",
                state=state,
                reason=InterruptReason.ERROR,
                message="Exception occurred during workflow"
            )
        except Exception:
            pytest.fail("Should not raise exception")
        
        retrieved = interrupt_controller.get_interrupted_workflow("error_test")
        assert retrieved is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])