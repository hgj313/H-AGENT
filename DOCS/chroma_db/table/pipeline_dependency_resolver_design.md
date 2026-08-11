# PipelineFactory 组件依赖自动适配方案

> 目标文件：`persistence/vector/implementation/pipeline_factory.py`
> 文档版本：v1.0
> 日期：2026/05/28

---

## 一、现有代码问题诊断

### 1.1 当前组件依赖关系图

```
PipelineFactory.create()
│
├── embedder (可选, 支持 type 字符串)
│   └── 工厂: EmbedderFactory.create(embedder_type, **embedder_kwargs)
│
├── storage (可选, 支持 type 字符串)
│   └── 工厂: VectorStoreFactory.create(storage_type, dimension=embedder.dimension, **storage_kwargs)
│
├── chunker (可选)
│   └── 默认: GeneralChunker(**chunker_kwargs)
│
├── searcher (可选)
│   └── 问题: 硬编码了 ChromaSearchEngine，不支持其他引擎
│       └── search_engine = ChromaSearchEngine(storage)  ← 只认 chroma
│
└── transaction_manager (可选, 支持 type 字符串)
    └── 工厂: TransactionManagerFactory.create(storage, storage_type)
```

### 1.2 当前初始化逻辑的问题清单

| # | 问题 | 层级 | 严重度 |
|---|---|---|---|
| P1 | `searcher is None` 时硬编码 `ChromaSearchEngine(storage)`，即使 `storage_type` 为其他值也会被忽略 | searcher/引擎层 | 高 |
| P2 | `search_engine` 和 `searcher` 互相独立初始化，无依赖关系建模，无法检测不兼容组合 | 全局 | 高 |
| P3 | 当用户只传 `storage_type="milvus"` 但 `search_engine=None` 时，searcher 会错误创建 Chroma 引擎 | 跨层冲突 | 高 |
| P4 | `embedder_type`、`storage_type`、`engine_type` 各自独立，无依赖传递推导 | 自动推导缺失 | 中 |
| P5 | 无警告机制，冲突发生时静默使用一个组件而忽略另一个（用户完全无感知） | 用户体验 | 高 |
| P6 | `VectorPipeline` 的 `create_searcher` 方法依赖 `self.storage` 和 `self.embedder`，但 factory 中 searcher 的创建依赖 `storage`，存在初始化顺序陷阱 | 初始化顺序 | 中 |
| P7 | 两个 Factory 类（`engine/factory.py` 和 `query/factory.py`）都叫 `SearchEngineFactory`，存在命名冲突风险 | 命名冲突 | 低 |

### 1.3 卡点详细分析

#### 卡点 1：搜索引擎层的硬编码问题

```python
# pipeline_factory.py L55-60
if searcher is None:
    if search_engine is None:
        search_engine = ChromaSearchEngine(storage)  # ← 硬编码，永远只创建 Chroma
    else:
        pass
    searcher = BaseVectorSearcher(search_engine)  # ← BaseVectorSearcher 不是类，直接实例化有问题
```

**问题**：
- `BaseVectorSearcher` 是 ABC（抽象基类），不能直接实例化
- 硬编码 `ChromaSearchEngine` 使 `storage_type` 的实际值被忽略

#### 卡点 2：跨层依赖冲突检测缺失

当用户调用：
```python
PipelineFactory.create(
    storage_type="milvus",
    search_engine=ChromaSearchEngine(...)  # 用户手动传入 chroma 引擎
)
```

系统应检测到 `milvus` storage + `chroma` engine 的不兼容组合，但当前不会检测，静默继续。

#### 卡点 3：自动推导缺失

当用户只指定：
```python
PipelineFactory.create(storage_type="milvus")
```

期望行为：自动将 `engine_type` 推导为 `milvus`（因为 `milvus` 存储需要配套的 `milvus` 搜索引擎）。当前行为：searcher 层使用 `ChromaSearchEngine`，导致运行时错误。

---

## 二、架构方案选型

### 2.1 方案对比

| 维度 | 方案 A：独立依赖校验适配层 | 方案 B：扩展现有协议规范 |
|---|---|---|
| **实现位置** | 新建 `DependencyResolver` 类 | 扩展 `PipelineConfig` + 各 Factory |
| **耦合度** | 低内聚，所有校验逻辑集中 | 高内聚，逻辑分散在各组件中 |
| **新增文件** | 1 个新文件 `dependency_resolver.py` | 0 个新文件，修改现有文件 |
| **扩展性** | 好，规则以数据驱动，新增组件只需注册规则 | 一般，新增组件需修改多处 |
| **复杂度** | 较高，需维护规则表和推导链 | 较低，逻辑直观 |
| **冲突修正透明性** | 好，所有修正集中在一处 | 一般，修正散落在各处 |
| **警告输出** | 集中，易于格式化 | 分散，需统一日志格式 |
| **测试难度** | 低，可针对 resolver 独立测试 | 高，需针对各 factory 组合测试 |

### 2.2 选型结论

**采用方案 A：独立依赖校验适配层**

理由：
1. 当前问题根源是"依赖关系处理割裂"，需要一个统一的协调者来掌握全局依赖视图
2. 数据驱动方式使新增组件只需注册规则，无需修改核心逻辑
3. 警告信息输出规范可集中管理，用户体验一致
4. 可独立测试，降低回归风险

---

## 三、依赖关系建模

### 3.1 组件分类

根据依赖关系，所有组件分为两类：

**独立组件（无上游依赖，可自由搭配）**

| 组件 | 说明 |
|---|---|
| `chunker` | 切分策略，不关心存储/引擎 |
| `embedder` | 向量化模型，不关心存储/引擎 |
| `id_generator` | ID命名策略，不关心存储/引擎 |

**依赖链组件（从根部向下游传递）**

```
storage_type (配置根，pipeline 必须有的依赖)
    ├── → storage (实例，依赖 storage_type + embedder.dimension)
    │        ├── → search_engine (依赖 storage 实例)
    │        └── → transaction_manager (依赖 storage 实例)
    │             └── → searcher (依赖 search_engine 实例)
    │
    └── → pipeline (聚合所有组件)
```

### 3.2 依赖层级详解

| 层级 | 组件 | 依赖关系 |
|---|---|---|
| 根部 | `storage_type` | 用户直接指定，是 pipeline 唯一必需的根依赖 |
| L1 | `storage` | 由 `storage_type` + `embedder.dimension` 决定 |
| L2 | `search_engine` | 由 `storage_type` 决定兼容类型，强依赖 storage 实例 |
| L2 | `transaction_manager` | 由 `storage_type` 决定兼容类型，强依赖 storage 实例 |
| L3 | `searcher` | 由 `storage_type` 决定兼容类型，依赖 search_engine 实例 |
| 上层 | `pipeline` | 聚合所有组件 |

### 3.3 依赖规则矩阵

```python
DEPENDENCY_RULES = {
    # 规则结构: ("storage_type") -> {下游组件兼容列表}
    # 含义: storage_type 决定了下游所有组件的兼容类型
    #       ——根部（storage_type）驱动整条依赖链适配
    "chroma": {
        "compatible_engines": ["chroma"],
        "compatible_searchers": ["chroma", "similarity"],
        "compatible_transaction_managers": ["chroma"],
    },
    "milvus": {
        "compatible_engines": ["milvus"],
        "compatible_searchers": ["milvus"],
        "compatible_transaction_managers": ["milvus"],
    },
    "qdrant": {
        "compatible_engines": ["qdrant"],
        "compatible_searchers": ["qdrant"],
        "compatible_transaction_managers": ["qdrant"],
    },
    # 默认规则（未在矩阵中定义的存储类型）
    "*": {
        "compatible_engines": ["chroma"],
        "compatible_searchers": ["similarity"],
        "compatible_transaction_managers": ["chroma"],
    },
}
```

### 3.4 自动推导规则

```python
AUTO_INFER_RULES = {
    # 当用户只指定 storage_type 时，自动推导下游组件类型
    "chroma": {
        "engine_type": "chroma",
        "searcher_type": "similarity",
        "transaction_type": "chroma",
    },
    "milvus": {
        "engine_type": "milvus",
        "searcher_type": "milvus",
        "transaction_type": "milvus",
    },
    "qdrant": {
        "engine_type": "qdrant",
        "searcher_type": "qdrant",
        "transaction_type": "qdrant",
    },
    # embedder.dimension 校验在 storage 创建时完成
}
```

### 3.5 关键约束

1. **pipeline 必须的根依赖：`storage_type`**（其余组件可自动推断）
2. **search_engine 和 transaction_manager 依赖 storage 实例**，而非仅依赖 storage_type——一旦 storage 实例创建完成，引擎兼容性就被固定
3. **冲突检测发生在 storage_type 层**，而不是 storage 实例层（从根部开始）
4. **独立组件**（chunker / embedder / id_generator）不参与依赖链推导，可自由搭配

---

## 四、冲突检测与修正执行逻辑

### 4.1 修正优先级（从根部 storage_type 开始）

```
storage_type (根部)
    ↓ 依赖链传递
storage → search_engine → searcher
storage → transaction_manager
```

冲突发生时，修正沿着依赖链向下游传递：
1. `storage_type` 冲突 → 直接修正 storage_type（最优先）
2. `search_engine` 与 `storage` 不兼容 → 以 storage 为准修正 search_engine
3. `searcher` 与 `search_engine` 不兼容 → 以 search_engine 为准修正 searcher
4. `transaction_manager` 与 `storage` 不兼容 → 以 storage 为准修正或降级

**核心原则**：`storage_type` 是唯一不可绕过的根依赖，从根部开始修正，依赖链向下游传递。独立组件（chunker / embedder / id_generator）不参与修正逻辑。

### 4.2 检测与修正流程

```
用户调用 create(storage_type="milvus", engine_type="chroma")
│
├── Step 1: 应用用户配置 + 自动推导
│   ├── 用户显式配置: storage_type="milvus", engine_type="chroma"
│   └── 自动推导: engine_type 应为 "milvus"（来自 storage_type="milvus" 的推导规则）
│
├── Step 2: 冲突检测
│   └── 查询 DEPENDENCY_RULES["milvus"]
│       └── 要求: compatible_engines = ["milvus"]
│       └── 发现: 用户配置的 "chroma" 不在兼容列表中 → 冲突
│
├── Step 3: 从根部修正（沿依赖链向下游传递）
│   ├── 修正点: engine_type（由 storage_type="milvus" 推导的正确值）
│   ├── 修正值: engine_type = "milvus"（以 storage_type 为准）
│   └── 生成警告: "[AUTO] engine_type='chroma' is incompatible with
│       storage_type='milvus', auto-corrected to 'milvus'. "
│       "(Resolution: storage_type is the root — downstream follows)"
│
├── Step 4: 继续初始化
│   ├── 创建 storage: MilvusVectorStorage(...)
│   └── 创建 search_engine: MilvusSearchEngine(storage)
│
└── Step 5: 返回 pipeline 实例，附带 adaptation_warnings 列表
```

### 4.3 修正决策树

```
检测到冲突 → 判断冲突类型 → 执行修正 → 记录警告

冲突类型分类:
├── storage_type 根部冲突
│   ├── 用户指定了不存在的 storage_type → 抛异常
│   └── 用户指定了新的 storage_type（无规则）→ 使用默认规则
│
├── engine 与 storage 不兼容
│   ├── 有替代 engine → 以 storage_type 为准修正 engine（依赖链传递）+ 警告
│   └── 无替代 engine → 抛异常
│
├── searcher 与 search_engine 不兼容
│   ├── 有替代 searcher → 以 search_engine 为准修正 searcher + 警告
│   └── 无替代 searcher → 创建通用 searcher + 警告
│
└── transaction_manager 与 storage 不兼容
    └── 以 storage_type 为准修正或降级 + 警告
```

---

## 五、警告信息输出规范

### 5.1 警告级别定义

| 级别 | 前缀 | 含义 | 处理方式 |
|---|---|---|---|
| `AUTO_CORRECTED` | `[AUTO]` | 自动修正成功，用户需知悉 | Info 日志 |
| `CONFIG_DEPRECATED` | `[DEPRECATED]` | 配置已废弃，请更换 | Warning 日志 |
| `INCOMPATIBLE` | `[INCOMPATIBLE]` | 不兼容组合，无法自动修正 | Error 日志 |
| `INVALID_CONFIG` | `[INVALID]` | 配置值无效 | Error 日志 |

### 5.2 警告信息格式

```python
# 模板
"[{level}] {component}.{field} = '{original_value}' is incompatible with {related_component}.{related_field} = '{related_value}'. Auto-corrected to: '{corrected_value}'. (Resolution: {reason})"

# 示例
"[AUTO] engine_type = 'chroma' is incompatible with storage_type = 'milvus'. Auto-corrected to: 'milvus'. (Resolution: storage_type is the root — downstream follows)"
```

### 5.3 警告数据结构

```python
class AdaptationWarning:
    level: str           # AUTO / DEPRECATED / INCOMPATIBLE / INVALID
    field: str           # 冲突的字段名
    original_value: str   # 用户原始配置
    corrected_value: str  # 修正后的值
    reason: str           # 修正原因
    component: str        # 冲突组件
    related_component: str # 关联组件
```

所有 warnings 在 Pipeline 初始化完成后汇总，可通过 `pipeline._adaptation_warnings` 访问。

---

## 六、具体实现步骤

### Step 1: 新建依赖解析器 `dependency_resolver.py`

路径: `persistence/vector/implementation/dependency_resolver.py`

```python
"""
依赖解析器 - 负责组件依赖的自动推导与冲突修正
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AdaptationWarning:
    level: str           # AUTO / DEPRECATED / INCOMPATIBLE / INVALID
    field: str           # 冲突的字段名
    original_value: any  # 用户原始配置
    corrected_value: any  # 修正后的值
    reason: str          # 修正原因
    component: str        # 冲突组件名
    related_component: str # 关联组件名

    def __str__(self) -> str:
        return (
            f"[{self.level}] {self.component}.{self.field} = '{self.original_value}' "
            f"is incompatible with {self.related_component}. "
            f"Auto-corrected to: '{self.corrected_value}'. "
            f"(Resolution: {self.reason})"
        )

class DependencyResolver:
    """
    依赖解析器 - 掌握全局依赖视图，负责冲突检测与自动修正
    """

    DEPENDENCY_RULES = {
        ("storage", "chroma"): {
            "compatible_engines": ["chroma"],
            "compatible_searchers": ["chroma", "similarity"],
            "compatible_transaction_managers": ["chroma"],
        },
        ("storage", "milvus"): {
            "compatible_engines": ["milvus"],
            "compatible_searchers": ["milvus"],
            "compatible_transaction_managers": ["milvus"],
        },
        ("storage", "qdrant"): {
            "compatible_engines": ["qdrant"],
            "compatible_searchers": ["qdrant"],
            "compatible_transaction_managers": ["qdrant"],
        },
        ("storage", "*"): {
            "compatible_engines": ["chroma"],
            "compatible_searchers": ["similarity"],
            "compatible_transaction_managers": ["chroma"],
        },
    }

    AUTO_INFER_RULES = {
        "chroma": {
            "engine_type": "chroma",
            "searcher_type": "similarity",
            "transaction_type": "chroma",
        },
        "milvus": {
            "engine_type": "milvus",
            "searcher_type": "milvus",
            "transaction_type": "milvus",
        },
        "qdrant": {
            "engine_type": "qdrant",
            "searcher_type": "qdrant",
            "transaction_type": "qdrant",
        },
    }

    def __init__(self):
        self._warnings: list[AdaptationWarning] = []

    @property
    def warnings(self) -> list[AdaptationWarning]:
        return list(self._warnings)

    def clear_warnings(self) -> None:
        self._warnings.clear()

    def resolve(self, config: dict) -> dict:
        """
        分析配置，执行依赖推导与冲突修正
        返回修正后的配置字典
        """
        self.clear_warnings()
        resolved = dict(config)  # 复制，不修改原始

        # Step 1: 从 storage_type 推导缺失的 engine/searcher/transaction_type
        resolved = self._auto_infer_from_storage_type(resolved)

        # Step 2: 校验 engine 与 storage 的兼容性
        resolved = self._validate_engine_storage_compat(resolved)

        # Step 3: 校验 searcher 与 engine 的兼容性
        resolved = self._validate_searcher_engine_compat(resolved)

        # Step 4: 校验 transaction_manager 与 storage 的兼容性
        resolved = self._validate_transaction_storage_compat(resolved)

        return resolved

    def _auto_infer_from_storage_type(self, config: dict) -> dict:
        storage_type = config.get("storage_type")
        if not storage_type:
            return config

        inferred = self.AUTO_INFER_RULES.get(storage_type, {})
        for target_field, inferred_value in inferred.items():
            if target_field not in config or config.get(target_field) is None:
                # 用户未指定，自动推导
                config[target_field] = inferred_value
            elif config[target_field] != inferred_value:
                # 用户指定了，但记录下来以便后续冲突检测
                pass  # 留到冲突检测阶段处理
        return config

    def _validate_engine_storage_compat(self, config: dict) -> dict:
        engine_type = config.get("engine_type")
        storage_type = config.get("storage_type")
        if not engine_type or not storage_type:
            return config

        rules = self.DEPENDENCY_RULES.get(storage_type,
                                          self.DEPENDENCY_RULES["*"])
        compatible = rules.get("compatible_engines", [])

        if engine_type not in compatible:
            original = engine_type
            # 自动修正为兼容的第一个选项（优先级：同 storage_type > 默认）
            corrected = storage_type  # engine_type 同 storage_type 命名
            self._warnings.append(AdaptationWarning(
                level="AUTO",
                field="engine_type",
                original_value=original,
                corrected_value=corrected,
                reason=f"storage_type is the root — engine follows",
                component="search_engine",
                related_component=f"storage_type({storage_type})"
            ))
            config["engine_type"] = corrected

        return config

    def _validate_searcher_engine_compat(self, config: dict) -> dict:
        searcher_type = config.get("searcher_type")
        engine_type = config.get("engine_type")
        if not searcher_type or not engine_type:
            return config

        # searcher 类型到 engine 类型的映射
        searcher_to_engine = {
            "chroma": "chroma",
            "similarity": "chroma",  # similarity searcher 可搭配 chroma engine
            "milvus": "milvus",
            "qdrant": "qdrant",
        }
        expected_engine = searcher_to_engine.get(searcher_type)
        if expected_engine and expected_engine != engine_type:
            original = searcher_type
            corrected = engine_type  # searcher 与 engine 对齐
            self._warnings.append(AdaptationWarning(
                level="AUTO",
                field="searcher_type",
                original_value=original,
                corrected_value=corrected,
                reason=f"searcher '{searcher_type}' only supports engine '{expected_engine}', got '{engine_type}'",
                component="searcher",
                related_component=f"search_engine({engine_type})"
            ))
            config["searcher_type"] = corrected

        return config

    def _validate_transaction_storage_compat(self, config: dict) -> dict:
        transaction_type = config.get("transaction_type")
        storage_type = config.get("storage_type")
        if not transaction_type or not storage_type:
            return config

        rules = self.DEPENDENCY_RULES.get(storage_type,
                                          self.DEPENDENCY_RULES["*"])
        compatible = rules.get("compatible_transaction_managers", [])

        if transaction_type not in compatible:
            original = transaction_type
            corrected = compatible[0] if compatible else "chroma"
            self._warnings.append(AdaptationWarning(
                level="AUTO",
                field="transaction_type",
                original_value=original,
                corrected_value=corrected,
                reason=f"transaction manager '{transaction_type}' incompatible with storage_type '{storage_type}'",
                component="transaction_manager",
                related_component=f"storage_type({storage_type})"
            ))
            config["transaction_type"] = corrected

        return config
```

### Step 2: 修改 `pipeline_factory.py`

```python
from persistence.vector.implementation.dependency_resolver import DependencyResolver, AdaptationWarning

class PipelineFactory:

    @classmethod
    def create(cls, ..., engine_type: str = None, searcher_type: str = None,
               transaction_type: str = None, **kwargs) -> VectorPipeline:

        # Step 0: 构建配置字典用于依赖解析
        raw_config = {
            "embedder": embedder,
            "storage": storage,
            "chunker": chunker,
            "searcher": searcher,
            "search_engine": search_engine,
            "transaction_manager": transaction_manager,
            "embedder_type": embedder_type,
            "storage_type": storage_type,
            "engine_type": engine_type,       # 新增
            "searcher_type": searcher_type,   # 新增
            "transaction_type": transaction_type,  # 新增
            "enable_async": enable_async,
            **kwargs
        }

        # Step 1: 依赖解析（自动推导 + 冲突修正）
        resolver = DependencyResolver()
        resolved = resolver.resolve(raw_config)

        # Step 2: 输出警告信息
        for warning in resolver.warnings:
            logging.warning(str(warning))

        # Step 3: 从解析后的配置中提取各组件
        embedder = resolved["embedder"]
        storage = resolved["storage"]
        # ... 提取其他组件 ...

        engine_type_resolved = resolved.get("engine_type")
        searcher_type_resolved = resolved.get("searcher_type")

        # Step 4: 创建 embedder（若未提供）
        if embedder is None:
            embedder_kwargs = kwargs.get("embedder_kwargs", {}) or {}
            embedder = EmbedderFactory.create(resolved["embedder_type"], **embedder_kwargs)

        # Step 5: 创建 storage（若未提供）
        if storage is None:
            storage_kwargs = kwargs.get("storage_kwargs", {}) or {}
            storage_kwargs.setdefault("dimension", embedder.dimension)
            storage = VectorStoreFactory.create(resolved["storage_type"], **storage_kwargs)

        # Step 6: 创建 engine（使用解析后的 engine_type）
        if search_engine is None and engine_type_resolved:
            storage_cls_name = type(storage).__name__
            if "Chroma" in storage_cls_name:
                search_engine = ChromaSearchEngine(storage)
            elif "Milvus" in storage_cls_name:
                search_engine = MilvusSearchEngine(storage)  # 待实现
            # ... 其他 engine ...

        # Step 7: 创建 searcher（使用解析后的 searcher_type）
        if searcher is None:
            if searcher_type_resolved == "similarity":
                searcher = SimilaritySearcher(
                    embedder=embedder,
                    storage=storage,
                    search_engine=search_engine
                )
            elif searcher_type_resolved == "chroma":
                searcher = ChromaVectorSearcher(
                    embedder=embedder,
                    storage=storage,
                    search_engine=search_engine
                )
            # ... 其他 searcher ...

        # Step 8: 创建 transaction_manager（使用解析后的 transaction_type）
        if transaction_manager is None and resolved.get("enable_transaction"):
            tm_type = resolved.get("transaction_type", resolved["storage_type"])
            transaction_manager = TransactionManagerFactory.create(storage, tm_type)

        # Step 9: 创建 pipeline，附加警告信息
        pipeline = AsyncVectorPipeline(...) if enable_async else VectorPipeline(...)

        # 将警告信息附加到 pipeline 实例
        pipeline._adaptation_warnings = resolver.warnings

        return pipeline
```

### Step 3: 修改 `VectorPipeline` / `AsyncVectorPipeline`

在 `__init__` 中接收并保存 `adaptation_warnings`：

```python
class VectorPipeline(BaseVectorPipeline):
    def __init__(self, ..., adaptation_warnings: list = None, **kwargs):
        super().__init__(...)
        self._adaptation_warnings = adaptation_warnings or []

    @property
    def adaptation_warnings(self) -> list[AdaptationWarning]:
        return self._adaptation_warnings
```

### Step 4: 在各 Factory 中注册新组件的依赖规则

当新增 `MilvusVectorStorage` 时，需要同步更新 `DependencyResolver.DEPENDENCY_RULES` 和 `AUTO_INFER_RULES`：

```python
DEPENDENCY_RULES["milvus"] = {
    "compatible_engines": ["milvus"],
    "compatible_searchers": ["milvus"],
    "compatible_transaction_managers": ["milvus"],
}

AUTO_INFER_RULES["milvus"] = {
    "engine_type": "milvus",
    "searcher_type": "milvus",
    "transaction_type": "milvus",
}
```

---

## 七、测试验证方案

### 7.1 单元测试

```python
# tests/test_dependency_resolver.py

import pytest
from persistence.vector.implementation.dependency_resolver import DependencyResolver, AdaptationWarning

class TestDependencyResolver:

    def test_auto_infer_from_storage_type_chroma(self):
        """当只指定 storage_type='chroma' 时，应自动推导 engine/searcher/transaction"""
        resolver = DependencyResolver()
        config = {"storage_type": "chroma"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "chroma"
        assert resolved["searcher_type"] == "similarity"
        assert resolved["transaction_type"] == "chroma"
        assert len(resolver.warnings) == 0

    def test_auto_infer_from_storage_type_milvus(self):
        """当只指定 storage_type='milvus' 时，应自动推导 milvus 相关组件"""
        resolver = DependencyResolver()
        config = {"storage_type": "milvus"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "milvus"
        assert resolved["searcher_type"] == "milvus"
        assert resolved["transaction_type"] == "milvus"

    def test_conflict_engine_storage_auto_correct(self):
        """检测到 engine 与 storage 不兼容时应自动修正"""
        resolver = DependencyResolver()
        config = {"storage_type": "milvus", "engine_type": "chroma"}
        resolved = resolver.resolve(config)

        # 应修正为 milvus
        assert resolved["engine_type"] == "milvus"
        assert len(resolver.warnings) == 1
        assert resolver.warnings[0].level == "AUTO"
        assert resolver.warnings[0].original_value == "chroma"
        assert resolver.warnings[0].corrected_value == "milvus"

    def test_conflict_transaction_storage_auto_correct(self):
        """检测到 transaction_manager 与 storage 不兼容时应自动修正"""
        resolver = DependencyResolver()
        config = {"storage_type": "milvus", "transaction_type": "chroma"}
        resolved = resolver.resolve(config)

        assert resolved["transaction_type"] == "milvus"
        warning = resolver.warnings[0]
        assert warning.level == "AUTO"
        assert "transaction_manager" in warning.component

    def test_no_warnings_when_all_compatible(self):
        """当所有组件都兼容时，不应产生警告"""
        resolver = DependencyResolver()
        config = {
            "storage_type": "chroma",
            "engine_type": "chroma",
            "searcher_type": "similarity",
            "transaction_type": "chroma"
        }
        resolved = resolver.resolve(config)
        assert len(resolver.warnings) == 0

    def test_multiple_warnings_accumulated(self):
        """多个冲突应全部被检测到并产生警告"""
        resolver = DependencyResolver()
        config = {
            "storage_type": "milvus",
            "engine_type": "chroma",
            "transaction_type": "chroma"
        }
        resolved = resolver.resolve(config)

        # 两个冲突应产生两个警告
        assert len(resolver.warnings) == 2
        warning_fields = {w.field for w in resolver.warnings}
        assert "engine_type" in warning_fields
        assert "transaction_type" in warning_fields

    def test_explicit_config_preserved_when_no_conflict(self):
        """当用户显式配置的值与推导值一致时，应保留用户配置"""
        resolver = DependencyResolver()
        config = {"storage_type": "chroma", "engine_type": "chroma"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "chroma"
        # 无警告，因为用户配置与推导值一致
        assert len(resolver.warnings) == 0

    def test_unknown_storage_type_uses_default_rules(self):
        """未知的 storage_type 应使用默认规则"""
        resolver = DependencyResolver()
        config = {"storage_type": "unknown_store"}
        resolved = resolver.resolve(config)

        # 应降级到 chroma 默认规则
        assert resolved["engine_type"] == "chroma"
        assert resolved["transaction_type"] == "chroma"
```

### 7.2 集成测试

```python
# tests/test_pipeline_factory_integration.py

import pytest
from persistence.vector.implementation.pipeline_factory import PipelineFactory

class TestPipelineFactoryIntegration:

    def test_create_with_only_storage_type(self):
        """仅指定 storage_type 时，所有上层组件应自动适配"""
        pipeline = PipelineFactory.create(storage_type="chroma")

        # storage 应该是 chroma
        assert type(pipeline.storage).__name__ == "ChromaVectorStorage"
        # engine 应该是 chroma
        assert pipeline._search_engine is not None
        # searcher 应该是 compatible 类型
        assert pipeline.searcher is not None

    def test_create_with_incompatible_combination_auto_fix(self):
        """传入不兼容组合时，应自动修正并警告"""
        import logging
        with pytest.assertLogs(level="WARNING") as log:
            pipeline = PipelineFactory.create(
                storage_type="milvus",
                engine_type="chroma"  # 不兼容，应被修正
            )

        # 检查警告输出
        warning_logs = [r.message for r in log.records if "[AUTO]" in r.message]
        assert len(warning_logs) > 0
        assert "engine_type" in warning_logs[0]

        # pipeline 仍然可用（已自动修正）
        assert pipeline.storage is not None
        assert pipeline._search_engine is not None

    def test_create_with_all_explicit_compatible(self):
        """所有组件都显式指定且兼容时，无警告"""
        pipeline = PipelineFactory.create(
            storage_type="chroma",
            engine_type="chroma",
            searcher_type="similarity",
            transaction_type="chroma"
        )

        assert len(pipeline._adaptation_warnings) == 0

    def test_async_pipeline_has_warnings(self):
        """异步 pipeline 也应支持警告机制"""
        pipeline = PipelineFactory.create(
            storage_type="milvus",
            engine_type="chroma",
            enable_async=True
        )

        assert len(pipeline._adaptation_warnings) > 0

    def test_dimension_mismatch_detection(self):
        """向量维度不匹配应在 storage 创建时检测"""
        # 此测试验证 dimension 校验逻辑未被破坏
        # 需配合 mock embedder 使用
```

---

## 八、扩展性保障

### 8.1 新增存储类型

当新增 `MilvusVectorStorage` 时，仅需：

1. 在 `VectorStoreFactory._REGISTRY` 注册
2. 在 `DependencyResolver.DEPENDENCY_RULES` 和 `AUTO_INFER_RULES` 添加规则：

```python
DEPENDENCY_RULES["milvus"] = {
    "compatible_engines": ["milvus"],
    "compatible_searchers": ["milvus"],
    "compatible_transaction_managers": ["milvus"],
}

AUTO_INFER_RULES["milvus"] = {
    "engine_type": "milvus",
    "searcher_type": "milvus",
    "transaction_type": "milvus",
}
```

3. 在 `SearchEngineFactory._REGISTRY` 注册对应的 `MilvusSearchEngine`
4. 在 `PipelineFactory.create` 的 engine 创建分支中添加 `MilvusSearchEngine` 的分支逻辑

### 8.2 新增 Embedder 类型

只需在 `EmbedderFactory._REGISTRY` 注册，无需修改依赖解析器（embedder 位于最底层，无上游依赖）。

### 8.3 新增 Searcher 类型

1. 实现新的 Searcher 类（继承 `BaseVectorSearcher`）
2. 在 `DependencyResolver.AUTO_INFER_RULES` 中注册推导关系
3. 在 `DependencyResolver.DEPENDENCY_RULES` 中添加兼容规则
4. 在 `PipelineFactory.create` 的 searcher 创建分支中添加分支逻辑

---

## 九、落地计划

| 阶段 | 任务 | 文件变更 |
|---|---|---|
| Phase 1 | 实现 `DependencyResolver` 类 | 新增 `dependency_resolver.py` |
| Phase 2 | 修改 `PipelineFactory.create` 方法签名，增加 `engine_type`、`searcher_type`、`transaction_type` 参数 | 修改 `pipeline_factory.py` |
| Phase 3 | 修改 `VectorPipeline` / `AsyncVectorPipeline`，增加 `adaptation_warnings` 属性 | 修改 `pipeline.py` |
| Phase 4 | 编写单元测试 `tests/test_dependency_resolver.py` | 新增测试文件 |
| Phase 5 | 编写集成测试 `tests/test_pipeline_factory_integration.py` | 新增测试文件 |
| Phase 6 | 代码 review 与优化 | — |

---

*文档结束*