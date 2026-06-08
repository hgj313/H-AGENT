"""入口校验节点（llm_react）的输入 Schema。

使用 Pydantic v2 定义 `LlmReactInput`，覆盖节点运行所需的全部必要输入信息。
双重用途：
1. 前端参数传入时，校验并构造合法的 DRState 状态对象
2. 非结构化输入场景下，配合 `bind_tools([LlmReactInput], tool_choice="required")`
   从自由文本中提取结构化字段
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class LlmReactInput(BaseModel):
    """设计审查流程的结构化输入。

    覆盖启动图流程所需的全部关键参数，任何字段缺失时节点将触发
    interrupt 交互或 LLM 兜底提取。
    """

    prd_file_path: Optional[str] = Field(
        default=None,
        description="PRD 文档的文件路径，支持本地绝对路径或可访问的 URL",
    )
    prd_raw_text: Optional[str] = Field(
        default=None,
        description="PRD 文档的原始文本内容（当无法提供文件路径时直接传入全文）",
    )
    image_path: Optional[List[str]] = Field(
        default=None,
        description="原型图资源地址列表，支持本地路径或图片 URL",
    )
    standard_queries: Optional[List[str]] = Field(
        default=None,
        description="设计标准检索关键词列表，用于 retrieve_standard 节点",
    )
    user_intent: Optional[str] = Field(
        default=None,
        description=(
            "用户的补充意图说明，例如 '先看PRD'、'跳过原型分析'、"
            "'只做PRD审查' 等。节点将据此设置 skip 标志或调整 plan"
        ),
    )
