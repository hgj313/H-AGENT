"""
Analyze Prototype Tool

分析原型图，结构化提取设计规范与强规符合性。

"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from llm_model.vision_model.aliyun import VisionModelProvider
from agent.graphs.design_review.schemas.prototype_schema import PrototypeAnalysis
from agent.graphs.design_review.tools.analyze_prototype.prompts import (
    ANALYZE_PROTOTYPE_PROMPT,
)

model_provider = VisionModelProvider()
_model = model_provider.get_model()


def _normalize_specs(args: dict) -> dict:
    """处理 specs 字段，将字符串值转换为 SpecItemWithConfidence 对象格式。"""
    import json
    
    specs = args.get("specs")
    if not specs or not isinstance(specs, dict):
        return args
    
    normalized = {}
    for key, value in specs.items():
        if isinstance(value, str):
            # 字符串转换为 SpecItemWithConfidence 格式
            normalized[key] = {
                "value": value,
                "confidence": "目测",
                "context": "",
                "compliance": "未标注",
            }
        elif isinstance(value, dict):
            # 已经是字典格式，确保必要字段存在
            normalized[key] = {
                "value": value.get("value", ""),
                "confidence": value.get("confidence", "目测"),
                "context": value.get("context", ""),
                "compliance": value.get("compliance", "未标注"),
            }
        else:
            normalized[key] = value
    
    args["specs"] = normalized
    return args


def _normalize_nested_objects(args: dict) -> dict:
    """处理嵌套对象字段，将字符串转换为字典格式。"""
    import json
    
    # 需要处理的嵌套对象字段
    nested_fields = ['components', 'visual', 'interaction', 'state', 'layout_nav']
    
    for field in nested_fields:
        if field in args and isinstance(args[field], str):
            try:
                parsed = json.loads(args[field])
                if isinstance(parsed, dict):
                    args[field] = parsed
            except (json.JSONDecodeError, TypeError):
                pass
    
    # 处理 permission.operation_permissions 字段（字符串转列表）
    if 'permission' in args and isinstance(args['permission'], dict):
        perm = args['permission']
        if 'operation_permissions' in perm and isinstance(perm['operation_permissions'], str):
            value = perm['operation_permissions']
            if value.strip():
                perm['operation_permissions'] = [value]
            else:
                perm['operation_permissions'] = []
    
    return args


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
@tool
def analyze_prototype(
    image_urls: Annotated[list[str], "待分析的图片 URL 列表"],
) -> dict:
    """
    分析原型图像。

    参数：
        image_urls: 图片 URL 列表，支持 https:// 或 oss:// 开头。
                    必须显式传入，工具内部不再从 state 中自动抽取。

    返回：
        视觉模型对每张图的 JSON 分析结果（中文描述），按 PrototypeAnalysis schema 约束。
    """
    if not image_urls:
        return {"error": "未检测到图片，无法执行原型分析。"}

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "你是一个专业的 UI 设计审查助手。分析用户提供的原型图，"
                "并调用 PrototypeAnalysis 工具返回结构化分析结果。"
                "你必须调用工具，不要直接回复文本。"
            ),
        },
    ]
    for image_url in image_urls:
        prompt_messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                    {
                        "type": "text",
                        "text": ANALYZE_PROTOTYPE_PROMPT,
                    },
                ],
            }
        )

    bound_model = _model.bind_tools(
        [PrototypeAnalysis],
        tool_choice="required",
        strict=True,
        parallel_tool_calls=False,
    )
    ai_message = bound_model.invoke(prompt_messages)

    tool_calls = getattr(ai_message, "tool_calls", None) or []
    if not tool_calls:
        # 保留兜底异常以便排错
        raise ValueError(
            "模型未调用 PrototypeAnalysis 工具。"
            f"原始 content: {getattr(ai_message, 'content', '')!r}"
        )

    target_args: dict | None = None
    for tc in tool_calls:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        if name in ("PrototypeAnalysis", "prototype_analysis"):
            args = (
                tc.get("args")
                if isinstance(tc, dict)
                else getattr(tc, "args", None)
            )
            if isinstance(args, dict):
                target_args = args
                break
    if target_args is None:
        # 退化取第一次 tool_call 的 args
        first = tool_calls[0]
        target_args = (
            first.get("args")
            if isinstance(first, dict)
            else getattr(first, "args", None)
        ) or {}

    # 严格 Pydantic 二次校验：bind_tools 已限定结构，此处再确保类型/必填字段
    # 处理模型返回格式不匹配的情况（如 specs 字段返回字符串而非对象）
    target_args = _normalize_specs(target_args)
    target_args = _normalize_nested_objects(target_args)
    parsed: PrototypeAnalysis = PrototypeAnalysis.model_validate(target_args)
    return parsed.model_dump()
