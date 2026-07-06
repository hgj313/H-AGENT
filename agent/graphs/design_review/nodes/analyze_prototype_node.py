"""
原型图分析节点：
- 读取 state.image_path 调用 analyze_prototype 工具
- 把模型原始输出解析后写入 state.prototype_analysis（含 raw/analysis/specs/meta）
- 维护 current_node / prototype_done / analysis_result（兼容字段）/ llm_calls
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage

from agent.graphs.design_review.states.dr_state import (
    DRState,
    SpecSource,
    make_empty_spec_source,
)
from agent.graphs.design_review.tools.analyze_prototype.analyze_prototype import (
    analyze_prototype,
)


_NODE_NAME = "analyze_prototype"


def _detect_image_in_message(last_msg) -> tuple[bool, list[str]]:
    if not isinstance(last_msg, HumanMessage):
        return False, []

    content = last_msg.content
    image_urls: list[str] = []

    if isinstance(content, str):
        return False, []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image_url":
                image_url = item.get("image_url", {})
                if isinstance(image_url, dict):
                    url = image_url.get("url", "")
                elif isinstance(image_url, str):
                    url = image_url
                else:
                    continue
                if url:
                    image_urls.append(url)

    return len(image_urls) > 0, image_urls


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
    # 优先新 schema 字段 "specs"，回退到旧版 "规格值"
    block = analysis.get("specs")
    if not isinstance(block, dict):
        block = analysis.get("规格值")
    if not isinstance(block, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for k, v in block.items():
        if isinstance(v, dict):
            normalized[k] = v
        else:
            normalized[k] = {"value": str(v), "context": ""}
    return normalized


class AnalyzePrototypeNode:
    @staticmethod
    def _is_trusted(state: DRState) -> bool:
        src = state.get("prototype_analysis") or {}
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
            return {"current_node": _NODE_NAME, "prototype_done": True}

        image_urls: list[str] = list(state.get("image_path") or [])

        if not image_urls:
            messages = state.get("messages") or []
            last_msg = messages[-1] if messages else None
            has_img, urls_from_msg = _detect_image_in_message(last_msg)
            if has_img:
                image_urls = urls_from_msg

        proto: SpecSource = dict(state.get("prototype_analysis") or make_empty_spec_source())
        proto["raw_content"] = image_urls
        proto["meta"] = {
            **(proto.get("meta") or {}),
            "node": _NODE_NAME,
            "started_at": datetime.utcnow().isoformat() + "Z",
        }

        if not image_urls:
            proto["is_ready"] = False
            proto["analysis"] = {"error": "未检测到原型图，请先上传图片或传入 image_path。"}
            node_err = {_NODE_NAME: "未检测到原型图，请先上传图片或传入 image_path。"}
            assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
            return {
                "current_node": _NODE_NAME,
                "prototype_analysis": proto,
                "prototype_done": False,
                "analysis_result": None,
                "error": "missing_image",
                "node_errors": node_err,
                "llm_calls": 0,
            }

        try:
            content = analyze_prototype.invoke({"image_urls": image_urls})
        except Exception as e:
            proto["is_ready"] = False
            proto["analysis"] = {"error": f"原型分析失败: {e}"}
            node_err = {_NODE_NAME: f"原型分析失败: {e}"}
            assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
            return {
                "current_node": _NODE_NAME,
                "prototype_analysis": proto,
                "prototype_done": False,
                "analysis_result": None,
                "error": f"prototype_invoke_error: {e}",
                "node_errors": node_err,
                "llm_calls": 1,
            }

        # 工具已通过 schema 约束直接返回 dict；兼容旧版可能返回 str 的情况
        if isinstance(content, str):
            parsed = _safe_parse_json(content)
            if isinstance(parsed, str):
                proto["analysis"] = {"raw_text": parsed, "specs_extracted": False}
                specs: dict[str, dict[str, Any]] = {}
            else:
                proto["analysis"] = parsed
                specs = _extract_specs(parsed)
        elif isinstance(content, dict):
            # 工具内部封装好的错误返回
            if set(content.keys()) == {"error"}:
                proto["is_ready"] = False
                proto["analysis"] = content
                proto["meta"]["finished_at"] = datetime.utcnow().isoformat() + "Z"
                proto["meta"]["image_count"] = len(image_urls)
                node_err = {_NODE_NAME: str(content["error"])}
                assert isinstance(node_err, dict), f"node_errors 类型非法: {type(node_err)}"
                return {
                    "current_node": _NODE_NAME,
                    "prototype_analysis": proto,
                    "prototype_done": False,
                    "analysis_result": None,
                    "error": str(content["error"]),
                    "node_errors": node_err,
                    "llm_calls": 0,
                }
            proto["analysis"] = content
            specs = _extract_specs(content)
        else:
            proto["analysis"] = {"raw_text": str(content), "specs_extracted": False}
            specs = {}

        proto["specs"] = specs
        proto["is_ready"] = bool(specs)
        proto["meta"]["finished_at"] = datetime.utcnow().isoformat() + "Z"
        proto["meta"]["image_count"] = len(image_urls)

        compat = None
        if isinstance(proto["analysis"], dict):
            compat = [proto["analysis"]]
        elif isinstance(proto["analysis"], list):
            compat = proto["analysis"]

        return {
            "current_node": _NODE_NAME,
            "prototype_analysis": proto,
            "prototype_done": bool(proto["is_ready"]),
            "analysis_result": compat,
            "llm_calls": 1,
        }
