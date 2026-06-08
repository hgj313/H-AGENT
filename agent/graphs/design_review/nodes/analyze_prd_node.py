"""
PRD 分析节点：
读取 prd_raw_text / prd_file_path / prd_analysis.raw_content，
调用 analyze_prd 工具，写入 prd_analysis。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from agent.graphs.design_review.states.dr_state import (
    DRState,
    SpecSource,
    make_empty_spec_source,
)
from agent.graphs.design_review.tools.analyze_prd.analyze_prd import analyze_prd


_NODE_NAME = "analyze_prd"


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


def _extract_specs(analysis: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(analysis, dict):
        return {}
    # 优先使用新 schema 字段 "specs"，兼容旧版 "规格值"
    block = analysis.get("specs")
    if not isinstance(block, dict):
        block = analysis.get("规格值")
    if not isinstance(block, dict):
        return {}
    # 统一转成 {key: {value, context}} 形态
    normalized: dict[str, dict[str, Any]] = {}
    for k, v in block.items():
        if isinstance(v, dict):
            normalized[k] = v
        else:
            normalized[k] = {"value": str(v), "context": ""}
    return normalized


class AnalyzePRDNode:
    @staticmethod
    def _is_trusted(state: DRState) -> bool:
        src = state.get("prd_analysis") or {}
        if not src:
            return False
        if not src.get("is_ready"):
            return False
        specs = src.get("specs")
        if not isinstance(specs, dict) or len(specs) == 0:
            return False
        analysis = src.get("analysis")
        if isinstance(analysis, dict) and "error" in analysis:
            return False
        return True

    def __call__(self, state: DRState) -> dict:
        if self._is_trusted(state):
            return {"current_node": _NODE_NAME, "prd_done": True}

        prd_src: SpecSource = dict(state.get("prd_analysis") or make_empty_spec_source())

        prd_text: str | None = None
        meta_extra: dict[str, Any] = {}

        if state.get("prd_raw_text"):
            prd_text = state["prd_raw_text"]
            meta_extra["source"] = "state.prd_raw_text"

        if not prd_text and isinstance(prd_src.get("raw_content"), str):
            prd_text = prd_src["raw_content"]
            meta_extra["source"] = "state.prd_analysis.raw_content"

        if not prd_text and state.get("prd_file_path"):
            prd_text = state["prd_file_path"]
            meta_extra["source"] = "state.prd_file_path"

        prd_src["meta"] = {
            **(prd_src.get("meta") or {}),
            "node": _NODE_NAME,
            "started_at": datetime.utcnow().isoformat() + "Z",
            **meta_extra,
        }

        if not prd_text and not state.get("prd_file_path"):
            prd_src["is_ready"] = False
            prd_src["analysis"] = {"error": "缺少 PRD 文本，请先传入 prd_raw_text 或 prd_file_path。"}
            node_err = {_NODE_NAME: "缺少 PRD 文本，请先传入 prd_raw_text 或 prd_file_path。"}
            assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
            return {
                "current_node": _NODE_NAME,
                "prd_analysis": prd_src,
                "prd_done": False,
                "error": "missing_prd_content",
                "node_errors": node_err,
                "llm_calls": 0,
            }

        prd_src["raw_content"] = prd_text or state.get("prd_file_path")

        try:
            # 优先使用文件路径，让工具内部读取文件
            if state.get("prd_file_path"):
                file_path = state["prd_file_path"]
                # 确保 file_path 是列表格式
                if isinstance(file_path, str):
                    file_path = [file_path]
                content = analyze_prd.invoke({"file_path": file_path})
            else:
                content = analyze_prd.invoke({"prd_content": prd_text})
        except Exception as e:
            prd_src["is_ready"] = False
            prd_src["analysis"] = {"error": f"PRD 分析失败: {e}"}
            node_err = {_NODE_NAME: f"PRD 分析失败: {e}"}
            assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
            return {
                "current_node": _NODE_NAME,
                "prd_analysis": prd_src,
                "prd_done": False,
                "error": f"prd_invoke_error: {e}",
                "node_errors": node_err,
                "llm_calls": 1,
            }

        # 工具已通过 schema 约束直接返回 dict；兼容旧版可能返回 str 的情况
        if isinstance(content, str):
            parsed = _safe_parse_json(content)
            if isinstance(parsed, str):
                prd_src["analysis"] = {"raw_text": parsed, "specs_extracted": False}
                specs: dict[str, dict[str, Any]] = {}
            else:
                prd_src["analysis"] = parsed
                specs = _extract_specs(parsed)
        elif isinstance(content, dict):
            prd_src["analysis"] = content
            specs = _extract_specs(content)
        else:
            prd_src["analysis"] = {"raw_text": str(content), "specs_extracted": False}
            specs = {}

        prd_src["specs"] = specs
        prd_src["is_ready"] = bool(specs)
        prd_src["meta"]["finished_at"] = datetime.utcnow().isoformat() + "Z"
        prd_src["meta"]["content_length"] = len(prd_text)

        # 如果 specs 为空，写入 node_errors 以便 _collect_failed_done_flags 检测
        node_err = {}
        if not prd_src["is_ready"]:
            node_err = {_NODE_NAME: "PRD 分析完成但未提取到 specs，请检查文档内容。"}

        return {
            "current_node": _NODE_NAME,
            "prd_analysis": prd_src,
            "prd_done": bool(prd_src["is_ready"]),
            "node_errors": node_err,
            "llm_calls": 1,
        }
