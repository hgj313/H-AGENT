"""
设计标准检索节点：
读取 state.standard_queries，调 retrive_standard 工具，写入 standard_rules。
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

try:
    from agent.graphs.design_review.tools.retrive_standard.retrive_standard import (
        retrive_standard,
    )
    _RETRIEVE_TOOL_OK = True
except Exception:
    retrive_standard = None  # type: ignore
    _RETRIEVE_TOOL_OK = False


_NODE_NAME = "retrieve_standard"


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
    block = analysis.get("规格值")
    if not isinstance(block, dict):
        return {}
    return block


class RetrieveStandardNode:
    @staticmethod
    def _is_trusted(state: DRState) -> bool:
        """判定 state 中是否已有可信的标准产物。

        满足以下全部条件才视为可信：
        1) standard_rules.is_ready == True
        2) standard_rules.specs 非空（至少有 1 条规格）
        3) standard_rules.analysis 不含 error 字段
        """
        std = state.get("standard_rules") or {}
        if not std:
            return False
        if not std.get("is_ready"):
            return False
        specs = std.get("specs")
        if not isinstance(specs, dict) or len(specs) == 0:
            return False
        analysis = std.get("analysis")
        if isinstance(analysis, dict) and "error" in analysis:
            return False
        return True

    def __call__(self, state: DRState) -> dict:
        # 早返回判定：基于"产物可信"而非 state.standard_done，避免上次失败时被误判为成功
        if self._is_trusted(state):
            return {"current_node": _NODE_NAME, "standard_done": True}

        std: SpecSource = dict(state.get("standard_rules") or make_empty_spec_source())

        queries: list[str] = []
        raw_queries = state.get("standard_queries")
        if isinstance(raw_queries, list):
            queries = [q for q in raw_queries if isinstance(q, str) and q.strip()]
        elif isinstance(raw_queries, str) and raw_queries.strip():
            queries = [raw_queries]

        std["meta"] = {
            **(std.get("meta") or {}),
            "node": _NODE_NAME,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "query_count": len(queries),
        }

        if not queries:
            std["is_ready"] = False
            std["analysis"] = {"error": "未提供查询词，跳过标准检索。"}
            node_err = {_NODE_NAME: "未提供查询词，跳过标准检索。"}
            assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
            return {
                "current_node": _NODE_NAME,
                "standard_rules": std,
                "standard_done": False,
                "error": "missing_standard_queries",
                "node_errors": node_err,
                "llm_calls": 0,
            }

        std["raw_content"] = queries

        try:
            if retrive_standard is None:
                raise RuntimeError("retrive_standard 工具不可用（依赖未安装或导入失败）")
            raw = retrive_standard.invoke({"query_texts": queries})
            content = getattr(raw, "content", raw) if raw is not None else ""
        except Exception as e:
            std["is_ready"] = False
            std["analysis"] = {"error": f"标准检索失败: {e}"}
            node_err = {_NODE_NAME: f"标准检索失败: {e}"}
            assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
            return {
                "current_node": _NODE_NAME,
                "standard_rules": std,
                "standard_done": False,
                "error": f"standard_invoke_error: {e}",
                "node_errors": node_err,
                "llm_calls": 1,
            }

        parsed = _safe_parse_json(content)
        if isinstance(parsed, str):
            std["analysis"] = {"raw_text": parsed, "specs_extracted": False}
            specs: dict[str, dict[str, Any]] = {}
        else:
            std["analysis"] = parsed
            specs = _extract_specs(parsed)

        std["specs"] = specs
        std["is_ready"] = bool(specs)
        std["meta"]["finished_at"] = datetime.utcnow().isoformat() + "Z"

        return {
            "current_node": _NODE_NAME,
            "standard_rules": std,
            "standard_done": bool(std["is_ready"]),
            "llm_calls": 1,
        }
