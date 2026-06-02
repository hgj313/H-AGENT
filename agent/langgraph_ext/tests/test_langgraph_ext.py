"""Tests for LangGraph Extension Framework

Unit tests and integration tests for:
- Tool Registration
- Middleware System
- Checkpoint Mechanism
- Persistence Layer
- Interrupt and Resume
"""

import pytest
import threading
import time
import json
from datetime import datetime
from typing import Any, TypedDict, Annotated
from operator import add

from agent.langgraph_ext.tools import (
    ToolRegistry,
    ToolValidator,
    ToolFactory,
    register_tool,
    get_tool,
    list_tools,
    PermissionLevel,
)
from agent.langgraph_ext.Middleware import (
    Middleware,
    MiddlewareChain,
    MiddlewareManager,
    LoggingMiddleware,
    ExceptionHandlerMiddleware,
    MiddlewareContext,
)
from agent.langgraph_ext.checkpoint import (
    CheckpointManager,
    Checkpoint,
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
    WorkflowState,
    WorkflowResumer,
)


class TestToolRegistration:
    """Tests for Tool Registration Module."""
    
    def test_registry_creation(self):
        registry = ToolRegistry()
        assert registry is not None
        assert len(registry._tools) == 0
    
    def test_register_function_as_tool(self):
        registry = ToolRegistry()
        
        def test_tool(x: int, y: int) -> int:
            return x + y
        
        tool_name = registry.register(test_tool, name="add_numbers")
        
        assert tool_name == "add_numbers"
        assert registry.get("add_numbers") is not None
        assert registry.get("add_numbers").name == "add_numbers"
    
    def test_register_with_metadata(self):
        registry = ToolRegistry()
        
        def greet(name: str) -> str:
            return f"Hello, {name}!"
        
        tool_name = registry.register(
            greet,
            name="greet_user",
            description="Greets a user by name",
            author="Test",
            tags=["greeting", "simple"]
        )
        
        registered = registry.get_registered_tool(tool_name)
        assert registered is not None
        assert registered.metadata.description == "Greets a user by name"
        assert "greeting" in registered.metadata.tags
        assert registered.metadata.author == "Test"
    
    def test_list_tools_with_filters(self):
        registry = ToolRegistry()
        
        def tool1(): pass
        def tool2(): pass
        def tool3(): pass
        
        registry.register(tool1, name="tool1", tags=["public"])
        registry.register(tool2, name="tool2", tags=["protected"], permission=PermissionLevel.PROTECTED)
        registry.register(tool3, name="tool3", tags=["private"], permission=PermissionLevel.PRIVATE)
        
        all_tools = registry.list_tools()
        assert len(all_tools) == 3
        
        public_tools = registry.list_tools(permission=PermissionLevel.PUBLIC)
        assert len(public_tools) == 1
        
        tagged_tools = registry.list_tools(tags=["public", "protected"])
        assert len(tagged_tools) == 2
    
    def test_tool_enable_disable(self):
        registry = ToolRegistry()
        
        def test_func(): return "result"
        
        registry.register(test_func, name="test_tool")
        
        assert registry.get("test_tool") is not None
        
        registry.disable("test_tool")
        assert not registry.get_registered_tool("test_tool").enabled
        
        registry.enable("test_tool")
        assert registry.get_registered_tool("test_tool").enabled
    
    def test_tool_aliases(self):
        registry = ToolRegistry()
        
        def my_tool(): pass
        
        registry.register(my_tool, name="my_tool")
        registry.add_alias("alias1", "my_tool")
        registry.add_alias("alias2", "my_tool")
        
        assert registry.get("alias1") is not None
        assert registry.get("alias2") is not None
    
    def test_tool_call_recording(self):
        registry = ToolRegistry()
        
        def simple_tool(): pass
        
        registry.register(simple_tool, name="simple_tool")
        
        registry.record_call("simple_tool")
        registry.record_call("simple_tool")
        registry.record_call("simple_tool", error=True)
        
        stats = registry.get_stats("simple_tool")
        assert stats['call_count'] == 3
        assert stats['error_count'] == 1
    
    def test_permission_checking(self):
        registry = ToolRegistry()
        
        def tool_func(): pass
        
        registry.register(tool_func, name="public_tool", permission=PermissionLevel.PUBLIC)
        registry.register(tool_func, name="private_tool", permission=PermissionLevel.PRIVATE)
        
        assert registry.check_permission("public_tool", PermissionLevel.PUBLIC)
        assert registry.check_permission("public_tool", PermissionLevel.PROTECTED)
        assert not registry.check_permission("private_tool", PermissionLevel.PUBLIC)


class TestToolValidator:
    """Tests for Tool Validator Module."""
    
    def test_validation_result(self):
        from agent.langgraph_ext.tools.validator import ValidationResult
        
        result = ValidationResult(is_valid=True, errors=[], warnings=["Warning 1"])
        assert result.is_valid
        assert result.has_warnings
        assert not result.has_errors
    
    def test_validate_params_with_required(self):
        validator = ToolValidator()
        
        required = ['param_a', 'param_b']
        result = validator.validate_params(
            "nonexistent_tool",
            {"param_a": 1},
            required_params=required
        )
        
        assert not result.is_valid
        assert len(result.errors) > 0


class TestMiddlewareSystem:
    """Tests for Middleware System."""
    
    def test_middleware_chain_creation(self):
        chain = MiddlewareChain()
        assert chain is not None
        assert len(chain._middlewares) == 0
    
    def test_add_middleware_to_chain(self):
        chain = MiddlewareChain()
        
        logging = LoggingMiddleware(name="test_log")
        chain.add(logging)
        
        assert len(chain._middlewares) == 1
        assert chain.get("test_log") is not None
    
    def test_middleware_enable_disable(self):
        chain = MiddlewareChain()
        
        logging = LoggingMiddleware(name="test_log")
        chain.add(logging)
        
        chain.disable("test_log")
        assert not chain.get("test_log").enabled
        
        chain.enable("test_log")
        assert chain.get("test_log").enabled
    
    def test_middleware_remove(self):
        chain = MiddlewareChain()
        
        logging = LoggingMiddleware(name="test_log")
        chain.add(logging)
        
        assert chain.remove("test_log")
        assert chain.get("test_log") is None
    
    @pytest.mark.asyncio
    async def test_middleware_chain_execution(self):
        chain = MiddlewareChain()
        
        class TestMiddleware(Middleware):
            async def _aprocess(self, context, state, next_handler):
                state['middleware_ran'] = True
                return await next_handler()
        
        chain.add(TestMiddleware(name="test"))
        
        async def final_handler():
            return {'result': 'success'}
        
        context = MiddlewareContext(graph_name="test")
        result = await chain.execute(context, {}, final_handler)
        
        assert result['result'] == 'success'
    
    def test_logging_middleware(self):
        logger = LoggingMiddleware(
            name="test_logger",
            log_level=10,
            log_timing=True
        )
        
        assert logger.name == "test_logger"
        assert logger.log_timing is True
    
    def test_exception_handler_middleware(self):
        def handle_error(error, context, state):
            return "handled"
        
        middleware = ExceptionHandlerMiddleware(
            name="error_handler",
            handlers={ValueError: handle_error},
            fallback_value="fallback"
        )
        
        assert middleware.name == "error_handler"
        assert middleware.fallback_value == "fallback"


class TestCheckpointManager:
    """Tests for Checkpoint Mechanism."""
    
    def test_checkpoint_manager_creation(self):
        manager = CheckpointManager()
        assert manager is not None
    
    def test_create_checkpoint(self):
        manager = CheckpointManager()
        
        state = {"messages": ["hello"], "count": 1}
        checkpoint = manager.create_checkpoint(
            state=state,
            run_id="test_run",
            trigger=CheckpointTrigger.MANUAL,
            node_name="test_node"
        )
        
        assert checkpoint is not None
        assert checkpoint.id is not None
        assert checkpoint.state == state
    
    def test_get_checkpoint_by_id(self):
        manager = CheckpointManager()
        
        state = {"data": "test"}
        checkpoint = manager.create_checkpoint(
            state=state,
            run_id="test_run",
            trigger=CheckpointTrigger.MANUAL
        )
        
        retrieved = manager.get_checkpoint(checkpoint.id)
        assert retrieved is not None
        assert retrieved.id == checkpoint.id
    
    def test_get_latest_checkpoint(self):
        manager = CheckpointManager()
        
        manager.create_checkpoint(state={"count": 1}, run_id="run1", trigger=CheckpointTrigger.MANUAL)
        checkpoint2 = manager.create_checkpoint(state={"count": 2}, run_id="run1", trigger=CheckpointTrigger.MANUAL)
        
        latest = manager.get_latest_checkpoint("run1")
        assert latest is not None
        assert latest.id == checkpoint2.id
    
    def test_list_checkpoints(self):
        manager = CheckpointManager()
        
        manager.create_checkpoint(state={"n": 1}, run_id="run1", trigger=CheckpointTrigger.MANUAL)
        manager.create_checkpoint(state={"n": 2}, run_id="run1", trigger=CheckpointTrigger.MANUAL)
        
        checkpoints = manager.list_checkpoints("run1")
        assert len(checkpoints) == 2
    
    def test_checkpoint_callback(self):
        manager = CheckpointManager()
        
        callback_called = []
        
        def callback(checkpoint):
            callback_called.append(checkpoint.id)
        
        manager.register_callback(CheckpointTrigger.MANUAL, callback)
        
        cp = manager.create_checkpoint(
            state={"test": True},
            run_id="run1",
            trigger=CheckpointTrigger.MANUAL
        )
        
        assert len(callback_called) == 1
        assert callback_called[0] == cp.id
    
    def test_condition_based_checkpointing(self):
        manager = CheckpointManager()
        
        manager.register_condition(
            "count_gt_5",
            lambda state: state.get("count", 0) > 5
        )
        
        assert manager.check_conditions({"count": 10}) == ["count_gt_5"]
        assert manager.check_conditions({"count": 3}) == []


class TestCheckpointStorage:
    """Tests for Checkpoint Storage."""
    
    def test_memory_storage(self):
        from agent.langgraph_ext.checkpoint.storage import MemoryCheckpointStorage
        
        storage = MemoryCheckpointStorage()
        manager = CheckpointManager(storage=storage)
        
        checkpoint = manager.create_checkpoint(
            state={"test": True},
            run_id="run1",
            trigger=CheckpointTrigger.MANUAL
        )
        
        retrieved = storage.load(checkpoint.id)
        assert retrieved is not None
        assert retrieved.id == checkpoint.id
    
    def test_checkpoint_serialization(self):
        manager = CheckpointManager()
        
        checkpoint = manager.create_checkpoint(
            state={"messages": ["hello"]},
            run_id="run1",
            trigger=CheckpointTrigger.MANUAL,
            node_name="test_node"
        )
        
        data = checkpoint.to_dict()
        assert data['id'] == checkpoint.id
        assert 'state' in data
        assert 'metadata' in data
        
        restored = Checkpoint.from_dict(data)
        assert restored.id == checkpoint.id


class TestPersistenceManager:
    """Tests for Persistence Layer."""
    
    def test_persistence_manager_creation(self):
        config = PersistenceConfig(backend=PersistenceBackend.MEMORY)
        manager = PersistenceManager(config)
        assert manager is not None
    
    def test_save_and_load_state(self):
        config = PersistenceConfig(backend=PersistenceBackend.MEMORY)
        manager = PersistenceManager(config)
        
        state = {"messages": ["hello"], "count": 42}
        record_id = manager.save_state(
            state=state,
            run_id="test_run",
            node_name="test_node"
        )
        
        loaded_state = manager.load_state(record_id)
        assert loaded_state == state
    
    def test_load_latest_state(self):
        config = PersistenceConfig(backend=PersistenceBackend.MEMORY)
        manager = PersistenceManager(config)
        
        manager.save_state(state={"n": 1}, run_id="run1")
        manager.save_state(state={"n": 2}, run_id="run1")
        
        latest = manager.load_latest_state("run1")
        assert latest['n'] == 2
    
    def test_state_history(self):
        config = PersistenceConfig(backend=PersistenceBackend.MEMORY)
        manager = PersistenceManager(config)
        
        from agent.langgraph_ext.persistence.persistence_manager import MemoryPersistenceBackend
        
        backend = MemoryPersistenceBackend()
        backend.save_state(type('StateRecord', (), {
            'id': '1', 'run_id': 'r1', 'thread_id': None,
            'node_name': 'n1', 'state_data': {'v': 1},
            'created_at': datetime.now(), 'updated_at': datetime.now(),
            'version': 1, 'checksum': None, 'metadata': {}
        })())
        
        states = backend.list_states("r1")
        assert len(states) >= 1


class TestInterruptController:
    """Tests for Interrupt and Resume Mechanism."""
    
    def test_interrupt_controller_creation(self):
        controller = InterruptController()
        assert controller is not None
    
    def test_request_interrupt(self):
        controller = InterruptController()
        
        interrupt_id = controller.request_interrupt(
            run_id="test_run",
            reason=InterruptReason.MANUAL,
            node_name="test_node",
            message="Test interrupt"
        )
        
        assert interrupt_id is not None
    
    def test_interrupt_workflow(self):
        controller = InterruptController()
        
        state = {"messages": ["hello"], "count": 1}
        workflow_state = controller.interrupt_workflow(
            run_id="test_run",
            state=state,
            reason=InterruptReason.MANUAL,
            current_node="test_node",
            message="Test interruption"
        )
        
        assert workflow_state is not None
        assert workflow_state.run_id == "test_run"
        assert workflow_state.interrupt_reason == InterruptReason.MANUAL
    
    def test_get_interrupted_workflow(self):
        controller = InterruptController()
        
        state = {"test": True}
        controller.interrupt_workflow(
            run_id="test_run",
            state=state,
            reason=InterruptReason.MANUAL
        )
        
        retrieved = controller.get_interrupted_workflow("test_run")
        assert retrieved is not None
        assert retrieved.run_id == "test_run"
    
    def test_list_interrupted_workflows(self):
        controller = InterruptController()
        
        controller.interrupt_workflow(run_id="run1", state={}, reason=InterruptReason.MANUAL)
        controller.interrupt_workflow(run_id="run2", state={}, reason=InterruptReason.USER_CONFIRMATION)
        
        interrupted = controller.list_interrupted_workflows()
        assert len(interrupted) == 2
    
    def test_breakpoints(self):
        controller = InterruptController()
        
        bp = controller.add_breakpoint(
            node_name="test_node",
            condition=lambda state: state.get("should_pause"),
            pause_on_entry=True,
            pause_on_exit=True
        )
        
        assert controller.check_breakpoint("test_node", {"should_pause": True}, is_entry=True)
        assert not controller.check_breakpoint("test_node", {"should_pause": False}, is_entry=True)
    
    def test_interrupt_handlers(self):
        controller = InterruptController()
        
        handler_called = []
        
        def handler(workflow_state):
            handler_called.append(workflow_state.run_id)
        
        controller.register_interrupt_handler(InterruptReason.ERROR, handler)
        
        controller.interrupt_workflow(
            run_id="test_run",
            state={},
            reason=InterruptReason.ERROR
        )
        
        assert len(handler_called) == 1
        assert handler_called[0] == "test_run"
    
    def test_validate_resume_point(self):
        controller = InterruptController()
        
        workflow_state = controller.interrupt_workflow(
            run_id="test_run",
            state={"messages": []},
            reason=InterruptReason.MANUAL
        )
        
        assert workflow_state is not None
        assert controller.get_interrupted_workflow("test_run") is not None
        
        resume_id = controller.create_resume_point("test_run")
        assert resume_id is not None
        
        is_valid, error = controller.validate_resume_point("test_run")
        assert is_valid, f"Expected valid but got error: {error}"


class TestWorkflowResumer:
    """Tests for Workflow Resumer."""
    
    def test_workflow_resumer_creation(self):
        resumer = WorkflowResumer()
        assert resumer is not None
    
    def test_resume_from_interrupt(self):
        controller = InterruptController()
        resumer = WorkflowResumer(interrupt_controller=controller)
        
        state = {"messages": ["hello"], "count": 1}
        controller.interrupt_workflow(
            run_id="test_run",
            state=state,
            reason=InterruptReason.MANUAL
        )
        
        result = resumer.resume_from_interrupt("test_run", lambda: None)
        
        assert result.success
        assert result.run_id == "test_run"
    
    def test_resume_hooks(self):
        resumer = WorkflowResumer()
        
        hook_called = []
        
        def hook(run_id, state):
            hook_called.append(run_id)
        
        resumer.register_resumption_hook("post", hook)
        
        result = resumer.resume_from_latest("nonexistent_run")
        
        assert len(hook_called) == 0


class TestIntegration:
    """Integration tests combining multiple modules."""
    
    def test_full_workflow_with_all_features(self):
        registry = ToolRegistry()
        
        def process_data(data: str) -> str:
            return f"Processed: {data}"
        
        registry.register(
            process_data,
            name="process_tool",
            description="Process input data",
            tags=["data", "processing"]
        )
        
        logging_mw = LoggingMiddleware(name="logger", log_timing=True)
        exception_mw = ExceptionHandlerMiddleware(
            name="error_handler",
            fallback_value={"error": "handled"}
        )
        
        chain = MiddlewareChain()
        chain.add(logging_mw)
        chain.add(exception_mw)
        
        checkpoint_manager = CheckpointManager()
        
        state = {
            "messages": ["hello"],
            "data": "test_data",
            "count": 0
        }
        
        cp1 = checkpoint_manager.create_checkpoint(
            state=state,
            run_id="integration_run",
            trigger=CheckpointTrigger.MANUAL,
            node_name="node1"
        )
        
        state["count"] = 1
        cp2 = checkpoint_manager.create_checkpoint(
            state=state,
            run_id="integration_run",
            trigger=CheckpointTrigger.ON_NODE_COMPLETE,
            node_name="node2"
        )
        
        persistence_config = PersistenceConfig(backend=PersistenceBackend.MEMORY)
        persistence_manager = PersistenceManager(persistence_config)
        
        record_id = persistence_manager.save_state(
            state=state,
            run_id="integration_run",
            node_name="node3"
        )
        
        interrupt_controller = InterruptController(
            checkpoint_manager=checkpoint_manager,
            persistence_manager=persistence_manager
        )
        
        workflow_state = interrupt_controller.interrupt_workflow(
            run_id="integration_run",
            state=state,
            reason=InterruptReason.USER_CONFIRMATION,
            current_node="node4",
            message="User confirmation needed"
        )
        
        resumer = WorkflowResumer(
            checkpoint_manager=checkpoint_manager,
            persistence_manager=persistence_manager,
            interrupt_controller=interrupt_controller
        )
        
        result = resumer.resume_from_interrupt("integration_run", lambda: None)
        
        assert result.success
        assert len(checkpoint_manager.list_checkpoints("integration_run")) >= 2
        assert len(persistence_manager.backend.list_states("integration_run")) >= 1
        assert len(interrupt_controller.list_interrupted_workflows()) >= 0
        
        tools = registry.to_langchain_tools()
        assert len(tools) >= 1
    
    def test_checkpoint_with_persistence(self):
        checkpoint_manager = CheckpointManager()
        
        persistence_manager = PersistenceManager(
            PersistenceConfig(backend=PersistenceBackend.MEMORY)
        )
        
        state = {"messages": ["hello"], "data": "test"}
        
        checkpoint = checkpoint_manager.create_checkpoint(
            state=state,
            run_id="test_run",
            trigger=CheckpointTrigger.MANUAL
        )
        
        persistence_manager.save_state(
            state=state,
            run_id="test_run",
            node_name="test_node"
        )
        
        loaded_cp = checkpoint_manager.get_checkpoint(checkpoint.id)
        loaded_state = persistence_manager.load_latest_state("test_run")
        
        assert loaded_cp is not None
        assert loaded_state is not None
    
    def test_interrupt_and_resume_workflow(self):
        checkpoint_manager = CheckpointManager()
        persistence_manager = PersistenceManager(
            PersistenceConfig(backend=PersistenceBackend.MEMORY)
        )
        interrupt_controller = InterruptController(
            checkpoint_manager=checkpoint_manager,
            persistence_manager=persistence_manager
        )
        
        state = {
            "messages": ["Starting workflow"],
            "step": 1,
            "completed": []
        }
        
        cp1 = checkpoint_manager.create_checkpoint(
            state=state,
            run_id="workflow_run",
            trigger=CheckpointTrigger.AUTOMATIC,
            node_name="step_1"
        )
        
        state["step"] = 2
        state["completed"].append("step_1")
        
        workflow_state = interrupt_controller.interrupt_workflow(
            run_id="workflow_run",
            state=state,
            reason=InterruptReason.USER_CONFIRMATION,
            current_node="step_2",
            message="Please confirm to continue"
        )
        
        resumer = WorkflowResumer(
            checkpoint_manager=checkpoint_manager,
            persistence_manager=persistence_manager,
            interrupt_controller=interrupt_controller
        )
        
        result = resumer.resume_from_interrupt("workflow_run", lambda: None)
        
        assert result.success
        assert result.resumed_state["step"] == 2


class TestPerformance:
    """Performance and stress tests."""
    
    def test_concurrent_checkpoint_creation(self):
        manager = CheckpointManager()
        results = []
        
        def create_checkpoints(count):
            for i in range(count):
                cp = manager.create_checkpoint(
                    state={"count": i},
                    run_id="concurrent_run",
                    trigger=CheckpointTrigger.MANUAL
                )
                results.append(cp.id)
        
        threads = [
            threading.Thread(target=create_checkpoints, args=(10,))
            for _ in range(5)
        ]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(results) == 50
    
    def test_rapid_state_saving(self):
        config = PersistenceConfig(backend=PersistenceBackend.MEMORY)
        manager = PersistenceManager(config)
        
        start_time = time.time()
        
        for i in range(100):
            manager.save_state(
                state={"iteration": i, "data": "x" * 100},
                run_id="perf_run"
            )
        
        elapsed = time.time() - start_time
        assert elapsed < 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])