# LangGraph Extension Framework

一个完整的 LangGraph 扩展框架，提供工具注册、中间件、检查点、持久化和打断恢复功能。

## 功能模块

### 1. 工具注册模块 (tools)

提供标准化的工具注册流程，支持：
- 动态工具注册
- 参数校验
- 权限管理（PUBLIC/PROTECTED/PRIVATE）
- 工具别名
- 使用统计

```python
from agent.langgraph_ext.tools import ToolRegistry, register_tool

registry = ToolRegistry()

def my_tool(data: str) -> str:
    return f"Processed: {data}"

registry.register(my_tool, name="my_tool", tags=["data"])

tools = registry.to_langchain_tools()
```

### 2. 中间件机制 (Middleware)

可扩展的中间件系统，支持：
- 日志记录
- 请求拦截
- 响应处理
- 异常捕获
- 限流和缓存
- 顺序配置和热插拔

```python
from agent.langgraph_ext.Middleware import (
    MiddlewareChain,
    LoggingMiddleware,
    ExceptionHandlerMiddleware,
)

chain = MiddlewareChain()
chain.add(LoggingMiddleware(name="logger"))
chain.add(ExceptionHandlerMiddleware(name="error_handler"))
```

### 3. 检查点功能 (checkpoint)

工作流执行过程中的检查点机制：
- 自动保存状态
- 上下文数据保留
- 执行进度跟踪
- 手动/自动触发
- 多存储后端支持

```python
from agent.langgraph_ext.checkpoint import (
    CheckpointManager,
    CheckpointConfig,
    CheckpointTrigger,
)

config = CheckpointConfig(auto_trigger_nodes=["process"])
manager = CheckpointManager(config=config)

checkpoint = manager.create_checkpoint(
    state={"data": "test"},
    run_id="workflow_001",
    trigger=CheckpointTrigger.MANUAL
)
```

### 4. 一级持久化方案 (persistence)

基于存储层的数据持久化：
- 多后端支持（Memory/File/SQLite）
- 数据压缩和校验
- 备份和恢复
- 清理策略

```python
from agent.langgraph_ext.persistence import (
    PersistenceManager,
    PersistenceConfig,
    PersistenceBackend,
)

config = PersistenceConfig(backend=PersistenceBackend.SQLITE)
manager = PersistenceManager(config)

record_id = manager.save_state(
    state={"messages": []},
    run_id="workflow_001"
)

state = manager.load_state(record_id)
```

### 5. 打断与恢复机制 (interrupt)

工作流的手动打断和恢复：
- 任意节点暂停
- 状态保留
- 从检查点恢复
- 打断原因跟踪

```python
from agent.langgraph_ext.interrupt import (
    InterruptController,
    WorkflowResumer,
    InterruptReason,
)

controller = InterruptController()
resumer = WorkflowResumer(interrupt_controller=controller)

# 中断工作流
workflow_state = controller.interrupt_workflow(
    run_id="workflow_001",
    state={"messages": []},
    reason=InterruptReason.MANUAL
)

# 恢复工作流
result = resumer.resume_from_interrupt("workflow_001", lambda: None)
```

## 目录结构

```
agent/langgraph_ext/
├── __init__.py          # 主入口
├── tools/               # 工具注册模块
│   ├── __init__.py
│   ├── registry.py      # 注册表核心
│   ├── validator.py     # 参数校验
│   └── factory.py       # 工具工厂
├── Middleware/           # 中间件模块
│   ├── __init__.py
│   ├── core.py          # 核心抽象
│   ├── interceptor.py   # 拦截器
│   └── manager.py       # 管理器
├── checkpoint/          # 检查点模块
│   ├── __init__.py
│   ├── manager.py      # 检查点管理
│   ├── storage.py      # 存储后端
│   └── trigger.py      # 触发策略
├── persistence/         # 持久化模块
│   ├── __init__.py
│   ├── persistence_manager.py  # 持久化管理
│   └── backup.py       # 备份管理
├── interrupt/           # 打断恢复模块
│   ├── __init__.py
│   ├── controller.py   # 中断控制器
│   └── resumer.py      # 恢复器
├── tests/              # 测试
│   ├── __init__.py
│   ├── test_langgraph_ext.py
│   └── test_integration.py
└── examples.py          # 使用示例
```

## 快速开始

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
from operator import add

from agent.langgraph_ext.tools import ToolRegistry
from agent.langgraph_ext.Middleware import MiddlewareChain, LoggingMiddleware
from agent.langgraph_ext.checkpoint import CheckpointManager, CheckpointConfig
from agent.langgraph_ext.persistence import PersistenceManager, PersistenceConfig
from agent.langgraph_ext.interrupt import InterruptController

class AgentState(TypedDict):
    messages: Annotated[list, add]
    step: int

# 初始化各模块
registry = ToolRegistry()
logging = LoggingMiddleware(name="logger")
checkpoint_manager = CheckpointManager(config=CheckpointConfig())
persistence_manager = PersistenceManager(config=PersistenceConfig())
interrupt_controller = InterruptController()

# 注册工具
def my_tool(data: str):
    return f"Processed: {data}"

registry.register(my_tool, name="my_tool")

# 创建图
graph = StateGraph(AgentState)
graph.add_node("agent", lambda state: {"messages": [], "step": state["step"] + 1})
graph.set_entry_point("agent")
graph.add_edge("agent", END)

compiled = graph.compile()
```

## 测试

运行单元测试：

```bash
python -m pytest agent/langgraph_ext/tests/test_langgraph_ext.py -v
```

运行集成测试：

```bash
python -m pytest agent/langgraph_ext/tests/test_integration.py -v
```

## 示例

查看 `examples.py` 获取完整的使用示例：

```bash
python agent/langgraph_ext/examples.py
```

## 架构设计

### 工具注册

```
ToolRegistry
├── 工具存储 (dict)
├── 工具别名映射
├── 权限控制
└── 统计追踪

ToolValidator
├── 参数校验
├── Schema 验证
└── 自定义验证器

ToolFactory
├── 规范创建
├── 函数包装
└── 组合工具
```

### 中间件链

```
MiddlewareChain
├── Middleware[]
│   ├── LoggingMiddleware
│   ├── ExceptionHandlerMiddleware
│   ├── RateLimitMiddleware
│   └── CachingMiddleware
└── 执行顺序控制
```

### 检查点

```
CheckpointManager
├── 配置管理
├── 检查点存储
├── 触发策略
│   ├── 手动触发
│   ├── 自动触发
│   ├── 条件触发
│   └── 错误触发
└── 回调机制
```

### 持久化

```
PersistenceManager
├── 配置管理
├── 状态缓存
├── 快照管理
└── 备份管理

BackupManager
├── 备份创建
├── 恢复
├── 清理策略
└── 导出/导入
```

### 打断恢复

```
InterruptController
├── 中断请求
├── 工作流状态管理
├── 断点管理
└── 处理程序注册

WorkflowResumer
├── 检查点恢复
├── 中断恢复
├── 状态验证
└── 恢复钩子
```

## 版本

当前版本：0.1.0

## 许可证

MIT