"""分析PRD文档内容"""
from __future__ import annotations

import json
import logging
from typing import Any
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage

from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider
from agent.graphs.design_review.tools.read_file import read_file_tool
from agent.graphs.design_review.schemas.prd_schema import PRDAnalysis, SpecItem
from .prompts import ANALYZE_PRD_PROMPT

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _normalize_list_field(value) -> list:
    """将字符串或列表统一转为列表格式。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        # 尝试解析 JSON 数组
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        # 按逗号或换行分割
        if value.strip():
            return [item.strip() for item in value.replace('\n', ',').split(',') if item.strip()]
    return []


def _normalize_bool_field(value) -> bool:
    """将字符串或其他类型统一转为布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', '是')
    return bool(value) if value else False


def _normalize_specs_field(value: Any) -> dict[str, SpecItem]:
    """将各种格式的 specs 数据规范化为 dict[str, SpecItem] 格式。"""
    if not value:
        return {}
    
    # 如果已经是正确的格式
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if isinstance(v, SpecItem):
                result[k] = v
            elif isinstance(v, dict):
                # 尝试转换为 SpecItem
                try:
                    result[k] = SpecItem(
                        value=str(v.get('value', '')),
                        context=str(v.get('context', ''))
                    )
                except Exception as e:
                    logger.warning(f"无法转换 specs 项 '{k}': {v}, 错误: {e}")
            elif isinstance(v, str):
                # 如果值是字符串，直接作为 value
                result[k] = SpecItem(value=v, context="")
            else:
                logger.warning(f"未知的 specs 值类型: {k} -> {type(v)}")
        return result
    
    # 如果是列表格式（可能是大模型输出的数组）
    if isinstance(value, list):
        result = {}
        for item in value:
            if isinstance(item, dict):
                name = item.get('name', item.get('key', ''))
                val = item.get('value', '')
                ctx = item.get('context', '')
                if name:
                    result[name] = SpecItem(value=str(val), context=str(ctx))
        return result
    
    # 如果是字符串（可能是 JSON 字符串）
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return _normalize_specs_field(parsed)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"无法解析 specs 字符串: {value[:100]}...")
    
    return {}


def _normalize_prd_args(args: dict) -> dict:
    """修正模型返回格式不匹配的问题。"""
    logger.debug(f"normalize_prd_args 输入: {json.dumps({k: type(v).__name__ for k, v in args.items()}, ensure_ascii=False)}")
    
    # 处理列表字段
    for field in ['to_confirm', 'unspecified_specs', 'potential_issues']:
        if field in args:
            args[field] = _normalize_list_field(args[field])
    
    # 处理嵌套对象中的布尔字段
    if 'data_format' in args and isinstance(args['data_format'], dict):
        df = args['data_format']
        if 'thousands_separator' in df:
            df['thousands_separator'] = _normalize_bool_field(df['thousands_separator'])
    
    # 兼容旧格式：将 "规格值" 映射到 "specs"
    if '规格值' in args and 'specs' not in args:
        logger.info("检测到旧格式 '规格值'，映射到 'specs'")
        args['specs'] = args.pop('规格值')
    
    # 规范化 specs 字段
    if 'specs' in args:
        original_specs = args['specs']
        args['specs'] = _normalize_specs_field(original_specs)
        if original_specs != args['specs']:
            logger.info(f"specs 字段已规范化: {type(original_specs).__name__} -> dict, 条目数: {len(args['specs'])}")
    
    logger.debug(f"normalize_prd_args 输出 specs 条目数: {len(args.get('specs', {}))}")
    return args


@tool
def analyze_prd(prd_content: str = "", file_path: list[str] = []) -> dict:
    """
    分析需求规格文档（PRD），并返回结构化 JSON 结果。
    大模型严格按 PRDAnalysis schema 输出，工具内部以 dict 返回。

    Args:
        prd_content: PRD文档内容 (可选,默认空字符串,能避免直接使用文件内容，就不使用，仅在file_path为空时使用该参数)
        file_path: PRD文档文件路径列表(可选,如果提供优先走文件内容，避免长上下传递)
    Returns:
        结构化分析结果（dict / JSON）。
    """
    logger.info(f"analyze_prd 开始执行, prd_content长度: {len(prd_content)}, file_path: {file_path}")
    
    if prd_content.strip() == "" and not file_path:
        raise ValueError(" prd_content 和 file_path 均未提供")

    reasoning_model = MinimaxReasoningModelProvider().get_model()
    if file_path:
        # 读取所有文件内容并合并
        contents = []
        for fp in file_path:
            if fp.strip():
                logger.info(f"读取文件: {fp}")
                content = read_file_tool.invoke({"file_path": fp.strip()})
                if content:
                    contents.append(f"## 文件: {fp}\n{content}")
                    logger.info(f"文件读取成功: {fp}, 内容长度: {len(content)}")
                else:
                    logger.warning(f"文件读取返回空内容: {fp}")
        prd_content = "\n\n".join(contents) if contents else prd_content

    logger.info(f"最终 prd_content 长度: {len(prd_content)}")

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
        strict=False,
        parallel_tool_calls=False,
    )
    
    logger.info("调用大模型进行 PRD 分析...")
    ai_message = bound_model.invoke(messages)

    tool_calls = getattr(ai_message, "tool_calls", None) or []
    logger.info(f"大模型返回 tool_calls 数量: {len(tool_calls)}")
    
    if not tool_calls:
        error_msg = (
            "模型未按 schema 调用工具（tool_choice=required 下不应发生）。"
            f"原始 content: {getattr(ai_message, 'content', '')!r}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    # 记录所有 tool_calls 的详细信息
    for i, tc in enumerate(tool_calls):
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
        logger.debug(f"tool_call[{i}]: name={name}, args_keys={list(args.keys()) if isinstance(args, dict) else 'N/A'}")

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
                logger.info(f"找到目标 tool_call: {name}")
                # 诊断日志：打完整 args（截断到 2000 字符），确认模型是真返回空 vs 没填
                logger.info(
                    f"LLM 完整 tool_call args: {json.dumps(args, ensure_ascii=False)[:2000]}"
                )
                break
    
    if target_args is None:
        first = tool_calls[0]
        target_args = (
            first.get("args")
            if isinstance(first, dict)
            else getattr(first, "args", None)
        ) or {}
        logger.warning("未找到 PRDAnalysis tool_call，使用第一个 tool_call 的 args")

    # 记录 specs 字段的原始状态
    if 'specs' in target_args:
        logger.info(f"原始 specs 字段类型: {type(target_args['specs']).__name__}, 值: {str(target_args['specs'])[:200]}")
    elif '规格值' in target_args:
        logger.info(f"检测到旧格式 '规格值' 字段，类型: {type(target_args['规格值']).__name__}")
    else:
        logger.warning("未检测到 specs 或 规格值 字段")

    # 修正格式不匹配的问题
    target_args = _normalize_prd_args(target_args)

    logger.info(f"normalize 后 specs 条目数: {len(target_args.get('specs', {}))}")

    try:
        parsed: PRDAnalysis = PRDAnalysis.model_validate(target_args)
        logger.info(f"PRDAnalysis 验证成功, specs 条目数: {len(parsed.specs)}")
    except Exception as e:
        logger.error(f"PRDAnalysis 验证失败: {e}")
        logger.error(f"target_args keys: {list(target_args.keys())}")
        raise

    return parsed.model_dump()
