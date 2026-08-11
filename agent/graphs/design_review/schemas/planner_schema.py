"""规划器节点的输出 Schema。

使用 Pydantic v2 定义 `PlannerDecision`，配合
`BaseChatModel.bind_tools([PlannerDecision], tool_choice="required", strict=True)`
约束大模型严格按 JSON 结构返回 plan 列表。
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class PlannerDecision(BaseModel):
    """规划器决策：返回本次需要执行的节点列表。"""

    plan: List[
        Literal[
            "analyze_prd",
            "retrieve_standard",
            "analyze_prototype",
            "generate_report",
        ]
    ] = Field(
        description="需要执行的分析节点列表，按需从可选节点中选取",
    )
