"""Tests for Infrastructure Module

Validates that infrastructure components work correctly after migration.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_checkpoint_manager():
    """Test checkpoint manager functionality"""
    print("Testing Checkpoint Manager...")
    
    from infrastructure.checkpoint import (
        CheckpointManager,
        CheckpointTrigger,
        CheckpointConfig,
        MemoryCheckpointStorage,
    )
    
    config = CheckpointConfig(max_checkpoints=5)
    storage = MemoryCheckpointStorage()
    manager = CheckpointManager(config=config, storage=storage)
    
    state = {"messages": [], "status": "init", "data": "test"}
    
    checkpoint = manager.create_checkpoint(
        state=state,
        run_id="test_run_1",
        trigger=CheckpointTrigger.MANUAL,
        node_name="test_node",
        description="Test checkpoint"
    )
    
    assert checkpoint is not None
    assert checkpoint.id is not None
    assert checkpoint.metadata.run_id == "test_run_1"
    assert checkpoint.metadata.node_name == "test_node"
    
    restored = manager.restore_checkpoint(checkpoint.id)
    assert restored is not None
    assert restored["data"] == "test"
    
    latest = manager.get_latest("test_run_1")
    assert latest is not None
    assert latest.id == checkpoint.id
    
    checkpoints = manager.list_checkpoints("test_run_1")
    assert len(checkpoints) >= 1
    
    print("✓ Checkpoint Manager test passed")
    return True


def test_checkpoint_trigger():
    """Test checkpoint trigger policy"""
    print("Testing Checkpoint Trigger Policy...")
    
    from infrastructure.checkpoint import (
        CheckpointTriggerPolicy,
        TriggerFrequency,
    )
    
    policy = CheckpointTriggerPolicy()
    
    error_count = [0]
    
    def error_condition(state):
        return state.get("error") is not None
    
    def always_condition(state):
        return True
    
    policy.add_trigger(
        name="on_error",
        condition=error_condition,
        frequency=TriggerFrequency.ONCE
    )
    
    should_trigger, triggered = policy.should_trigger(
        {"error": "test error"},
        node_name="test_node"
    )
    
    assert should_trigger is True
    assert "on_error" in triggered
    
    should_trigger, triggered = policy.should_trigger(
        {"status": "running"},
        node_name="test_node"
    )
    
    assert should_trigger is False
    
    print("✓ Checkpoint Trigger Policy test passed")
    return True


def test_persistence_manager():
    """Test persistence manager"""
    print("Testing Persistence Manager...")
    
    from infrastructure.persistence import (
        PersistenceManager,
        PersistenceConfig,
        MemoryPersistenceBackend,
    )
    
    config = PersistenceConfig(max_history_size=10)
    backend = MemoryPersistenceBackend()
    manager = PersistenceManager(config=config, backend=backend)
    
    record = manager.save_state(
        run_id="test_run",
        state_data={"key": "value", "count": 1}
    )
    
    assert record is not None
    assert record.run_id == "test_run"
    assert record.state_data["key"] == "value"
    
    latest = manager.load_latest("test_run")
    assert latest is not None
    assert latest.state_data["count"] == 1
    
    history = manager.get_history("test_run", limit=5)
    assert len(history) >= 1
    
    print("✓ Persistence Manager test passed")
    return True


def test_interrupt_controller():
    """Test interrupt controller"""
    print("Testing Interrupt Controller...")
    
    from infrastructure.interrupt import (
        InterruptController,
        InterruptReason,
        WorkflowState,
    )
    
    controller = InterruptController()
    
    interrupt_id = controller.request_interrupt(
        run_id="test_run",
        reason=InterruptReason.USER_CONFIRMATION,
        message="Please confirm",
        node_name="sensitive_node"
    )
    
    assert interrupt_id is not None
    
    state = {"messages": [], "status": "executing", "data": "processing"}
    
    workflow_state = controller.interrupt_workflow(
        run_id="test_run",
        state=state,
        reason=InterruptReason.USER_CONFIRMATION,
        current_node="sensitive_node",
        message="Confirm deletion",
        save_checkpoint=False
    )
    
    assert workflow_state is not None
    assert workflow_state.run_id == "test_run"
    assert workflow_state.interrupt_reason == InterruptReason.USER_CONFIRMATION
    
    retrieved = controller.get_interrupted_workflow("test_run")
    assert retrieved is not None
    assert retrieved.current_node == "sensitive_node"
    
    controller.set_interrupt_decision(interrupt_id, "approve", {"user": "admin"})
    decision = controller.get_interrupt_decision(interrupt_id)
    
    assert decision is not None
    assert decision["decision"] == "approve"
    
    print("✓ Interrupt Controller test passed")
    return True


def test_middleware():
    """Test middleware functionality"""
    print("Testing Middleware...")
    
    from infrastructure.middleware import (
        MiddlewareManager,
        MiddlewareContext,
        MiddlewareChain,
        Middleware,
        MiddlewareOrder,
    )
    
    class TestMiddleware(Middleware):
        async def _aprocess(self, context, state, next_handler):
            return await next_handler()
        
        def _process(self, context, state, next_handler):
            return next_handler()
    
    manager = MiddlewareManager()
    
    context = manager.create_context(
        graph_name="test_graph",
        node_name="test_node",
        run_id="test_run"
    )
    
    assert context.graph_name == "test_graph"
    assert context.node_name == "test_node"
    
    test_mw = TestMiddleware(name="test")
    
    manager.register("test", test_mw, nodes=["test_node"])
    
    assert len(manager.get_node_chain("test_node").list_middlewares()) >= 1
    
    def test_handler():
        return {"result": "success"}
    
    result = manager.execute_node(
        "test_node",
        context,
        {"test": "state"},
        test_handler
    )
    
    assert result["result"] == "success"
    
    print("✓ Middleware test passed")
    return True


def test_workflow_resumer():
    """Test workflow resumer"""
    print("Testing Workflow Resumer...")
    
    from infrastructure.interrupt import (
        WorkflowResumer,
        ResumptionConfig,
    )
    
    from infrastructure.checkpoint import CheckpointManager, MemoryCheckpointStorage
    
    checkpoint_manager = CheckpointManager(storage=MemoryCheckpointStorage())
    resumer = WorkflowResumer(checkpoint_manager=checkpoint_manager)
    
    state = {"messages": [], "status": "executing", "retry_count": 0}
    
    from infrastructure.checkpoint import CheckpointTrigger
    
    checkpoint = checkpoint_manager.create_checkpoint(
        state=state,
        run_id="test_run",
        trigger=CheckpointTrigger.MANUAL,
        node_name="test_node"
    )
    
    config = ResumptionConfig(validate_state=True, reset_counters=True)
    result = resumer.resume_from_checkpoint(
        checkpoint_id=checkpoint.id,
        graph_executor=lambda: None,
        config=config
    )
    
    assert result.success is True
    assert result.resumed_state["resumed_from"] == checkpoint.id
    assert "retry_count" in result.resumed_state
    
    print("✓ Workflow Resumer test passed")
    return True


def run_all_tests():
    """Run all infrastructure tests"""
    print("\n" + "="*60)
    print("Running Infrastructure Tests")
    print("="*60 + "\n")
    
    tests = [
        test_checkpoint_manager,
        test_checkpoint_trigger,
        test_persistence_manager,
        test_interrupt_controller,
        test_middleware,
        test_workflow_resumer,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} failed: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)