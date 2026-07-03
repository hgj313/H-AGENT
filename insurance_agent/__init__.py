"""Insurance Agent Package

独立能力模块 (Invoice Recognition Capability)。

目录分层（按通用性 / 职责）：
- domain/             领域模型（纯数据，无依赖）
- tools/              通用工具（可被任意 Agent 复用）
- infrastructure/     基础设施（与外部系统对接：PDF、LLM、OCR、存储）
- extractors/         提取策略（按格式分类）
- agents/             Agent 业务逻辑（按 capability 组织）
  - invoice_recognition/
    - states/         状态定义
    - nodes/          业务节点
    - tools/          该 capability 专属工具
- graph/              LangGraph 编排
- data/               格式注册表持久化

本模块遵循：
- DI 原则：所有外部依赖通过构造器注入
- DDD 分层：domain 永远不依赖 infrastructure
- LangGraph 模式：Graph = 编排，Node = 业务，State = 单一真源
"""
