"""LangGraph Extension Framework - 使用指南与示例

本文档提供了 LangGraph Extension Framework 的完整使用指南，包括：
1. 快速开始
2. 工具注册
3. 中间件系统
4. 检查点机制
5. 持久化层
6. 打断与恢复
7. 完整示例
"""

from agent.langgraph_ext.tools import (
    ToolRegistry,
    ToolValidator,
    register_tool,
    get_tool,
    list_tools,
    PermissionLevel,
)
from agent.langgraph_ext.Middleware import (
    LoggingMiddleware,
    ExceptionHandlerMiddleware,
    MiddlewareChain,
    MiddlewareManager,
    MiddlewareContext,
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
    WorkflowState,
)


def example_quick_start():
    """快速开始示例"""
    from langgraph.graph import StateGraph, END
    from typing import TypedDict, Annotated
    from operator import add
    
    class AgentState(TypedDict):
        messages: Annotated[list, add]
        step: int
    
    registry = ToolRegistry()
    
    def my_tool(data: str) -> str:
        return f"Processed: {data}"
    
    registry.register(
        my_tool,
        name="process_tool",
        description="Process input data",
        tags=["data", "processing"]
    )
    
    graph = StateGraph(AgentState)
    
    def agent_node(state):
        return {"messages": [], "step": state["step"] + 1}
    
    graph.add_node("agent", agent_node)
    graph.set_entry_point("agent")
    graph.add_edge("agent", END)
    
    compiled = graph.compile()
    
    tools = registry.to_langchain_tools()
    print(f"Registered {len(tools)} tools")
    return compiled


def example_tool_registration():
    """工具注册完整示例"""
    
    registry = ToolRegistry()
    
    def add_numbers(a: int, b: int) -> int:
        """Add two numbers together."""
        return a + b
    
    def greet(name: str) -> str:
        """Greet a user by name."""
        return f"Hello, {name}!"
    
    def process_data(data: str, options: dict = None) -> dict:
        """Process data with optional configurations."""
        options = options or {}
        return {"result": data.upper(), "options": options}
    
    registry.register(
        add_numbers,
        name="add",
        description="Add two numbers",
        tags=["math", "basic"]
    )
    
    registry.register(
        greet,
        name="greet",
        description="Greet a user",
        tags=["greeting"],
        permission=PermissionLevel.PROTECTED
    )
    
    registry.register(
        process_data,
        name="process",
        description="Process data with options",
        tags=["data"],
        enabled=True
    )
    
    print("Registered tools:")
    for tool in registry.list_tools():
        print(f"  - {tool.metadata.name}: {tool.metadata.description}")
    
    tool = registry.get("add")
    print(f"\nRetrieved tool: {tool.name}")
    
    stats = registry.get_stats("add")
    print(f"Tool stats: {stats}")
    
    tools = registry.to_langchain_tools()
    return tools


def example_middleware_system():
    """中间件系统完整示例"""
    
    chain = MiddlewareChain()
    
    logging = LoggingMiddleware(
        name="agent_logger",
        log_level=20,
        log_timing=True,
        log_state=False
    )
    
    exception_handler = ExceptionHandlerMiddleware(
        name="error_handler",
        handlers={
            ValueError: lambda e, ctx, s: {"error": str(e)},
            RuntimeError: lambda e, ctx, s: {"error": "Runtime error occurred"}
        },
        fallback_value={"error": "Unknown error"},
        reraise=False
    )
    
    chain.add(logging)
    chain.add(exception_handler)
    
    print(f"Middleware chain contains {len(chain._middlewares)} middleware")
    
    context = MiddlewareContext(
        graph_name="example_graph",
        node_name="agent",
        thread_id="thread_001"
    )
    
    async def final_handler():
        return {"result": "success", "data": "processed"}
    
    import asyncio
    result = asyncio.run(chain.execute(context, {}, final_handler))
    print(f"Result: {result}")
    
    chain.disable("agent_logger")
    print("Logger disabled")
    
    chain.enable("agent_logger")
    print("Logger enabled")
    
    return chain


def example_checkpoint_system():
    """检查点机制完整示例"""
    
    config = CheckpointConfig(
        enabled=True,
        auto_trigger_nodes=["analyze", "process"],
        trigger_on_error=True,
        max_checkpoints=100
    )
    
    manager = CheckpointManager(config=config)
    
    checkpoint_callbacks = []
    
    def on_checkpoint(checkpoint):
        checkpoint_callbacks.append(checkpoint.id)
        print(f"Checkpoint created: {checkpoint.id[:8]}... at {checkpoint.metadata.node_name}")
    
    manager.register_callback(CheckpointTrigger.AUTOMATIC, on_checkpoint)
    manager.register_callback(CheckpointTrigger.ON_NODE_COMPLETE, on_checkpoint)
    
    state = {
        "messages": ["Hello"],
        "data": {"items": []},
        "step": 0
    }
    
    cp1 = manager.create_checkpoint(
        state=state,
        run_id="workflow_001",
        trigger=CheckpointTrigger.MANUAL,
        node_name="start",
        description="Initial checkpoint"
    )
    
    state["step"] = 1
    state["data"]["items"].append("item1")
    
    cp2 = manager.create_checkpoint(
        state=state,
        run_id="workflow_001",
        trigger=CheckpointTrigger.ON_NODE_COMPLETE,
        node_name="process",
        tags=["production"]
    )
    
    state["step"] = 2
    
    manager.register_condition(
        "data_complete",
        lambda s: len(s.get("data", {}).get("items", [])) >= 2
    )
    
    if manager.check_conditions(state):
        cp3 = manager.create_checkpoint(
            state=state,
            run_id="workflow_001",
            trigger=CheckpointTrigger.ON_CONDITION,
            node_name="analyze"
        )
    
    checkpoints = manager.list_checkpoints("workflow_001")
    print(f"\nTotal checkpoints: {len(checkpoints)}")
    
    latest = manager.get_latest_checkpoint("workflow_001")
    print(f"Latest checkpoint at: {latest.metadata.node_name}")
    
    restored_state = manager.get_checkpoint(cp1.id)
    print(f"Restored state step: {restored_state.state['step']}")
    
    return manager, checkpoints


def example_persistence_layer():
    """持久化层完整示例"""
    
    config = PersistenceConfig(
        backend=PersistenceBackend.MEMORY,
        auto_save=True,
        save_interval_seconds=30,
        compress_data=True,
        enable_checksum=True
    )
    
    manager = PersistenceManager(config)
    
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
            "created_at": "2024-01-01T00:00:00"
        }
    }
    
    record_id = manager.save_state(
        state=workflow_state,
        run_id="workflow_001",
        thread_id="thread_001",
        node_name="agent"
    )
    print(f"Saved state: {record_id[:8]}...")
    
    loaded = manager.load_state(record_id)
    print(f"Loaded state: {loaded['context']['user_id']}")
    
    latest = manager.load_latest_state("workflow_001", "thread_001")
    print(f"Latest state: {latest is not None}")
    
    snapshot_id = manager.create_snapshot(
        run_id="workflow_001",
        thread_id="thread_001"
    )
    print(f"Created snapshot: {snapshot_id[:8]}...")
    
    return manager


def example_interrupt_and_resume():
    """打断与恢复完整示例"""
    
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
            state["results"].append(f"step_{step}_result")
            
            checkpoint_manager.create_checkpoint(
                state=state.copy(),
                run_id="workflow_001",
                trigger=CheckpointTrigger.AUTOMATIC,
                node_name=f"step_{step}"
            )
            
            if step == 2:
                print(f"Interrupting at step {step}...")
                workflow_state = interrupt_controller.interrupt_workflow(
                    run_id="workflow_001",
                    state=state.copy(),
                    reason=InterruptReason.USER_CONFIRMATION,
                    current_node=f"step_{step}",
                    message="Please confirm to continue"
                )
                print(f"Workflow interrupted at {workflow_state.current_node}")
                break
        
        return state
    
    final_state = simulate_workflow()
    
    interrupted = interrupt_controller.list_interrupted_workflows()
    print(f"Interrupted workflows: {len(interrupted)}")
    
    resumer = WorkflowResumer(
        checkpoint_manager=checkpoint_manager,
        persistence_manager=persistence_manager,
        interrupt_controller=interrupt_controller
    )
    
    is_valid, error = interrupt_controller.validate_resume_point("workflow_001")
    print(f"Resume point valid: {is_valid}")
    
    if is_valid:
        result = resumer.resume_from_interrupt("workflow_001", lambda: None)
        print(f"Resumption successful: {result.success}")
        print(f"Resumed state step: {result.resumed_state.get('step', 0)}")
    
    return interrupt_controller, resumer


def example_full_integration():
    """完整集成示例"""
    from langgraph.graph import StateGraph, END
    from typing import TypedDict, Annotated, Any
    from operator import add
    from langchain_core.messages import HumanMessage, AIMessage
    
    class WorkflowState(TypedDict):
        messages: Annotated[list, add]
        data: dict
        step: int
        checkpoint_count: int
    
    print("=== LangGraph Extension Framework - 完整集成示例 ===\n")
    
    print("1. 初始化工具注册表")
    registry = ToolRegistry()
    
    def transform_tool(data: str) -> str:
        return f"transformed_{data}"
    
    def analyze_tool(data: str) -> dict:
        return {"analysis": f"analyzed_{data}", "confidence": 0.95}
    
    registry.register(transform_tool, name="transform", tags=["data"])
    registry.register(analyze_tool, name="analyze", tags=["analysis"])
    
    print(f"   注册了 {len(registry.list_tools())} 个工具")
    
    print("\n2. 配置中间件")
    logging = LoggingMiddleware(name="workflow_logger", log_timing=True)
    exception_handler = ExceptionHandlerMiddleware(
        name="error_handler",
        fallback_value={"error": "handled"}
    )
    
    chain = MiddlewareChain()
    chain.add(logging)
    chain.add(exception_handler)
    
    print(f"   中间件链包含 {len(chain._middlewares)} 个中间件")
    
    print("\n3. 配置检查点管理器")
    checkpoint_config = CheckpointConfig(
        auto_trigger_nodes=["process", "analyze"],
        trigger_on_error=True
    )
    checkpoint_manager = CheckpointManager(config=checkpoint_config)
    print("   检查点管理器已初始化")
    
    print("\n4. 配置持久化管理器")
    persistence_config = PersistenceConfig(
        backend=PersistenceBackend.MEMORY,
        auto_save=True
    )
    persistence_manager = PersistenceManager(persistence_config)
    print("   持久化管理器已初始化")
    
    print("\n5. 配置中断控制器")
    interrupt_controller = InterruptController(
        checkpoint_manager=checkpoint_manager,
        persistence_manager=persistence_manager
    )
    print("   中断控制器已初始化")
    
    print("\n6. 创建工作流图")
    
    def process_node(state: WorkflowState) -> dict:
        new_state = {
            **state,
            "step": state["step"] + 1,
            "checkpoint_count": state.get("checkpoint_count", 0) + 1
        }
        
        if new_state["step"] % 2 == 0:
            checkpoint_manager.create_checkpoint(
                state=new_state,
                run_id="integration_test",
                trigger=CheckpointTrigger.AUTOMATIC,
                node_name=f"process_step_{new_state['step']}"
            )
        
        persistence_manager.save_state(
            state=new_state,
            run_id="integration_test",
            node_name=f"process_step_{new_state['step']}"
        )
        
        return new_state
    
    def should_continue(state: WorkflowState) -> str:
        if state["step"] >= 5:
            return END
        return "process"
    
    graph = StateGraph(WorkflowState)
    graph.add_node("process", process_node)
    graph.set_entry_point("process")
    graph.add_conditional_edges("process", should_continue, {"process": "process", END: END})
    
    compiled = graph.compile()
    print("   工作流图已编译")
    
    print("\n7. 模拟工作流执行")
    
    initial_state = {
        "messages": [HumanMessage(content="Start")],
        "data": {"input": "test"},
        "step": 0,
        "checkpoint_count": 0
    }
    
    state = initial_state
    for i in range(3):
        state = process_node(state)
        print(f"   执行步骤 {state['step']}，检查点计数: {state['checkpoint_count']}")
    
    print("\n8. 模拟中断和恢复")
    
    workflow_state = interrupt_controller.interrupt_workflow(
        run_id="integration_test",
        state=state,
        reason=InterruptReason.MANUAL,
        current_node="process",
        message="Manual interruption for testing"
    )
    
    print(f"   工作流已中断于节点: {workflow_state.current_node}")
    
    resumer = WorkflowResumer(
        checkpoint_manager=checkpoint_manager,
        persistence_manager=persistence_manager,
        interrupt_controller=interrupt_controller
    )
    
    result = resumer.resume_from_interrupt("integration_test", lambda: None)
    print(f"   恢复成功: {result.success}")
    
    print("\n=== 集成示例完成 ===")
    
    return {
        "registry": registry,
        "chain": chain,
        "checkpoint_manager": checkpoint_manager,
        "persistence_manager": persistence_manager,
        "interrupt_controller": interrupt_controller,
        "graph": compiled
    }


if __name__ == "__main__":
    print("运行示例...\n")
    
    print("=" * 60)
    print("快速开始示例")
    print("=" * 60)
    example_quick_start()
    
    print("\n" + "=" * 60)
    print("工具注册示例")
    print("=" * 60)
    example_tool_registration()
    
    print("\n" + "=" * 60)
    print("中间件系统示例")
    print("=" * 60)
    example_middleware_system()
    
    print("\n" + "=" * 60)
    print("检查点机制示例")
    print("=" * 60)
    example_checkpoint_system()
    
    print("\n" + "=" * 60)
    print("持久化层示例")
    print("=" * 60)
    example_persistence_layer()
    
    print("\n" + "=" * 60)
    print("打断与恢复示例")
    print("=" * 60)
    example_interrupt_and_resume()
    
    print("\n" + "=" * 60)
    print("完整集成示例")
    print("=" * 60)
    example_full_integration()