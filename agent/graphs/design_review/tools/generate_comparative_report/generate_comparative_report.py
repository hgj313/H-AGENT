"""生成对比审查报告工具。

通过 Pydantic Schema（位于 `agent.graphs.design_review.schemas.report_schema`）
约束大模型严格按 JSON 结构返回。
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider
from agent.graphs.design_review.schemas.report_schema import GenerateComparativeReport
from agent.graphs.design_review.tools.generate_comparative_report.prompts import (
    GENERATE_COMPARISON_REPORT_PROMPT,
)

_model = MinimaxReasoningModelProvider().get_model()

# 模块级加载静态标准 JSON——避免每次调用都读磁盘
_STANDARD_JSON_PATH = (
    Path(__file__).resolve().parent.parent / "retrive_standard" / "产品设计标准文档规范提取.json"
)
_DEFAULT_STANDARD_RULES: str = json.dumps(
    json.loads(_STANDARD_JSON_PATH.read_text(encoding="utf-8")),
    ensure_ascii=False,
)


@tool
def generate_comparative_report(
    prd_specs: str,
    prototype_specs: str,
    standard_rules: str = _DEFAULT_STANDARD_RULES,
) -> dict:
    """
    生成对比报告。

    Args:
        prd_specs: PRD 规格 (必填)
        prototype_specs: 原型图规格 (必填)
        standard_rules: 产品设计标准文档 (必填)
    Returns:
        结构化对比报告（dict / JSON），按 GenerateComparativeReport schema 约束。
    """
    prompt = GENERATE_COMPARISON_REPORT_PROMPT.format(
        prd_specs, prototype_specs, standard_rules
    )

    # 严格约束：把 GenerateComparativeReport 包装为 tool，强制模型必须 tool_choice="required" 调用
    bound_model = _model.bind_tools(
        [GenerateComparativeReport],
        tool_choice="required",
        strict=True,
        parallel_tool_calls=False,
    )
    ai_message = bound_model.invoke(prompt)

    tool_calls = getattr(ai_message, "tool_calls", None) or []
    if not tool_calls:
        raise ValueError(
            "模型未按 schema 调用工具（tool_choice=required 下不应发生）。"
            f"原始 content: {getattr(ai_message, 'content', '')!r}"
        )

    target_args: dict | None = None
    for tc in tool_calls:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        if name in ("GenerateComparativeReport", "generate_comparative_report"):
            args = (
                tc.get("args")
                if isinstance(tc, dict)
                else getattr(tc, "args", None)
            )
            if isinstance(args, dict):
                target_args = args
                break
    if target_args is None:
        first = tool_calls[0]
        target_args = (
            first.get("args")
            if isinstance(first, dict)
            else getattr(first, "args", None)
        ) or {}

    # 严格 Pydantic 二次校验
    parsed = GenerateComparativeReport.model_validate(target_args)
    return parsed.model_dump(by_alias=True)
