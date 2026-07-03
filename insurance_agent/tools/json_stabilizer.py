"""JSON 输出稳定化工具（AGENTS.md 三重保险中的第 2/3 道）

策略：
1. parse_json_strict: 多重尝试解析 LLM 输出的 JSON
2. build_tool_schema_response_format: 构造"伪工具调用"的 schema
   - 让 LLM 把字段填进工具参数里（强迫结构化输出）
"""

import json
import re
from typing import Any


def parse_json_strict(raw: str) -> dict:
    """多重尝试解析 LLM 返回的 JSON

    尝试顺序：
    1. 直接 json.loads
    2. 提取 Markdown ```json ... ``` 块
    3. 提取最外层 {...} 或 [...]
    """
    if not raw:
        return {"_error": "empty_string"}

    # Method 1: 直接解析
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Method 2: Markdown 块
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(1))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Method 3: 最外层 { ... }
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            result = json.loads(m.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return {"_error": "json_parse_failed", "_raw": raw[:500]}


def build_tool_schema_response_format(person_schema: dict) -> dict:
    """构造"伪工具调用" schema（用于 DashScope response_format 字段）

    思路：把要返回的对象包装成一个"工具"，
    让 LLM 通过填充工具参数的方式返回结构化结果。
    """
    return {
        "type": "function",
        "function": {
            "name": "submit_extraction_result",
            "description": "提交保险单人员提取结果",
            "parameters": {
                "type": "object",
                "properties": {
                    "insurance_company": {"type": "string"},
                    "policy_number": {"type": "string"},
                    "overall_start_date": {"type": "string"},
                    "overall_end_date": {"type": "string"},
                    "insured_persons": {
                        "type": "array",
                        "items": person_schema,
                    },
                },
                "required": ["insured_persons"],
            },
        },
    }
