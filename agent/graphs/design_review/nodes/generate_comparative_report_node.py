"""
对比审查报告生成节点：
读 prd_analysis / prototype_analysis / standard_rules，组装 prompt 调 LLM，
解析 JSON 写 state.report。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from agent.graphs.design_review.states.dr_state import (
    DRState,
    get_prd,
    get_prototype,
    get_standard,
)
from agent.graphs.design_review.tools.generate_comparative_report.prompts import (
    GENERATE_COMPARISON_REPORT_PROMPT,
)


_NODE_NAME = "generate_report"


def _safe_parse_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return text


def _excerpt(analysis: Any, max_len: int = 2000) -> str:
    if analysis is None:
        return ""
    try:
        s = json.dumps(analysis, ensure_ascii=False)
    except Exception:
        s = str(analysis)
    return s if len(s) <= max_len else s[:max_len] + "..."


def _build_prompt_inputs(state: DRState) -> dict[str, str]:
    prd = get_prd(state)
    proto = get_prototype(state)
    std = get_standard(state)

    return {
        "prd_specs": json.dumps(
            {
                "specs": prd.get("specs") or {},
                "raw_excerpt": _excerpt(prd.get("analysis")),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "prototype_specs": json.dumps(
            {
                "specs": proto.get("specs") or {},
                "raw_excerpt": _excerpt(proto.get("analysis")),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "standard_rules": json.dumps(
            {
                "specs": std.get("specs") or {},
                "raw_excerpt": _excerpt(std.get("analysis")),
                "raw_content": std.get("raw_content"),
            },
            ensure_ascii=False,
            indent=2,
        ),
    }


def _invoke_llm(prompt: str) -> str:
    try:
        from langchain_core.messages import HumanMessage
        try:
            from llm_model.reasoning_model.minimax import MinimaxReasoningModelProvider
            model = MinimaxReasoningModelProvider().get_model()
        except Exception:
            return json.dumps(
                {"error": "LLM 不可用：reasoning_model 依赖未安装"},
                ensure_ascii=False,
            )
        result = model.invoke([HumanMessage(content=prompt)])
        return getattr(result, "content", str(result))
    except Exception as e:
        return json.dumps({"error": f"LLM 调用失败: {e}"}, ensure_ascii=False)


class GenerateComparativeReportNode:
    @staticmethod
    def _is_trusted(state: DRState) -> bool:
        report = state.get("report")
        if not isinstance(report, dict) or not report:
            return False
        if "error" in report:
            return False
        if "items" not in report and "summary" not in report:
            return False
        return True

    def __call__(self, state: DRState) -> dict:
        if self._is_trusted(state):
            return {"current_node": _NODE_NAME, "report_done": True}

        prd = get_prd(state)
        proto = get_prototype(state)
        std = get_standard(state)

        if not (prd.get("is_ready") and proto.get("is_ready") and std.get("is_ready")):
            node_err = {_NODE_NAME: "前置数据未就绪，无法生成报告。"}
            assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
            return {
                "current_node": _NODE_NAME,
                "report": {
                    "error": "前置数据未就绪，无法生成报告。",
                    "prd_ready": prd.get("is_ready", False),
                    "prototype_ready": proto.get("is_ready", False),
                    "standard_ready": std.get("is_ready", False),
                },
                "report_done": False,
                "error": "dependencies_not_ready",
                "node_errors": node_err,
                "llm_calls": 0,
            }

        prompt_inputs = _build_prompt_inputs(state)
        prompt = GENERATE_COMPARISON_REPORT_PROMPT.format(**prompt_inputs)

        try:
            raw_text = _invoke_llm(prompt)
        except Exception as e:
            node_err = {_NODE_NAME: f"LLM 调用失败: {e}"}
            assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
            return {
                "current_node": _NODE_NAME,
                "report": {"error": f"LLM 调用失败: {e}"},
                "report_done": False,
                "error": f"report_invoke_error: {e}",
                "node_errors": node_err,
                "llm_calls": 1,
            }

        parsed = _safe_parse_json(raw_text)
        if not isinstance(parsed, dict):
            parsed = {
                "report_meta": {"generated_at": datetime.utcnow().isoformat() + "Z"},
                "raw_text": raw_text,
                "parse_failed": True,
            }
        else:
            parsed.setdefault("report_meta", {})
            parsed["report_meta"].setdefault(
                "generated_at", datetime.utcnow().isoformat() + "Z"
            )
            parsed["report_meta"].setdefault("standard_source", "产品设计标准文档V2.0")

        return {
            "current_node": _NODE_NAME,
            "report": parsed,
            "report_done": True,
            "llm_calls": 1,
        }
