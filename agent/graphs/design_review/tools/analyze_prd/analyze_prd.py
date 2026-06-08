"""分析PRD文档内容"""
from __future__ import annotations

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage

from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider
from agent.graphs.design_review.tools.read_file import read_file_tool
from agent.graphs.design_review.schemas.prd_schema import PRDAnalysis
from .prompts import ANALYZE_PRD_PROMPT


@tool
def analyze_prd(prd_content: str = "", file_path: list = []) -> dict:
    """
    分析需求规格文档（PRD），并返回结构化 JSON 结果。
    大模型严格按 PRDAnalysis schema 输出，工具内部以 dict 返回。

    Args:
        prd_content: PRD文档内容 (可选,默认空字符串,能避免直接使用文件内容，就不使用，仅在file_path为空时使用该参数)
        file_path: PRD文档文件路径(可选,默认空字符串,如果提供优先走文件内容，避免长上下传递)
    Returns:
        结构化分析结果（dict / JSON）。
    """
    if prd_content.strip() == "" and file_path.strip() == "":
        raise ValueError(" prd_content 和 file_path 均未提供")

    reasoning_model = MinimaxReasoningModelProvider().get_model()
    if file_path:
        prd_content = read_file_tool.invoke({"file_path": file_path})

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个专业的需求分析助手。分析用户提供的 PRD 文档，"
                "并调用 PRDAnalysis 工具返回结构化分析结果。"
                "你必须调用工具，不要直接回复文本。"
            ),
        },
        HumanMessage(
            content=ANALYZE_PRD_PROMPT.format(prd_content=prd_content),
        ),
    ]

    bound_model = reasoning_model.bind_tools(
        [PRDAnalysis],
        tool_choice="required",
        strict=True,
        parallel_tool_calls=False,
    )
    ai_message = bound_model.invoke(messages)

    tool_calls = getattr(ai_message, "tool_calls", None) or []
    if not tool_calls:
        raise ValueError(
            "模型未按 schema 调用工具（tool_choice=required 下不应发生）。"
            f"原始 content: {getattr(ai_message, 'content', '')!r}"
        )

    target_args: dict | None = None
    for tc in tool_calls:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        if name in ("PRDAnalysis", "prd_analysis"):
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

    parsed: PRDAnalysis = PRDAnalysis.model_validate(target_args)
    return parsed.model_dump()
