"""Design Review 相关的输出 Schema 集合。

对外仅暴露聚合根（顶层模型），子结构由各 schema 文件内部定义：
- `llm_react_schema` → LlmReactInput
- `planner_schema` → PlannerDecision
- `prd_schema` → PRDAnalysis
- `prototype_schema` → PrototypeAnalysis
- `report_schema` → GenerateComparativeReport
"""
from .llm_react_schema import LlmReactInput
from .planner_schema import PlannerDecision
from .prd_schema import PRDAnalysis
from .prototype_schema import PrototypeAnalysis
from .report_schema import GenerateComparativeReport

__all__ = [
    "LlmReactInput",
    "PlannerDecision",
    "PRDAnalysis",
    "PrototypeAnalysis",
    "GenerateComparativeReport",
]
