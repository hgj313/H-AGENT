"""llm_react_resume 节点：处理 interrupt 用户响应，更新 state 中的材料字段。

由图的条件边驱动：
- 响应"取消" → 设置 error，路由到 END
- 响应"继续" → 设置 skip 标志，路由到 planner
- 响应"追加/更改" → 更新材料字段，路由回 llm_react 重新检测

本节点不做 interrupt——interrupt 由 llm_react 节点负责。
"""
from __future__ import annotations

from typing import Any

from agent.graphs.design_review.nodes.llm_react_node import (
    _detect_has_prd,
    _detect_has_prototype,
)
from agent.graphs.design_review.states.dr_state import DRState

_NODE_NAME = "llm_react_resume"


class LlmReactResumeNode:
    """处理 interrupt 用户响应，更新 state 中的材料字段。"""

    @staticmethod
    def __call__(state: DRState) -> dict:
        resume_data = state.get("_resume_data")  # type: ignore[typeddict-item]
        if not resume_data or not isinstance(resume_data, dict):
            return {"current_node": _NODE_NAME}

        action = resume_data.get("action", "")

        if action == "取消":
            return {
                "current_node": _NODE_NAME,
                "input_validated": False,
                "error": "user_cancelled",
            }

        patch: dict[str, Any] = {"current_node": _NODE_NAME}

        new_prd_file = resume_data.get("prd_file_path")
        new_prd_text = resume_data.get("prd_raw_text")
        new_images = resume_data.get("image_path")

        if new_prd_file:
            patch["prd_file_path"] = new_prd_file
        if new_prd_text:
            patch["prd_raw_text"] = new_prd_text
        if new_images:
            patch["image_path"] = (
                [new_images] if isinstance(new_images, str) else new_images
            )

        if action == "继续":
            has_prd = _detect_has_prd({**state, **patch})
            has_prototype = _detect_has_prototype({**state, **patch})
            if not has_prd and not has_prototype:
                return patch
            patch["input_validated"] = True
            patch["skip_prd"] = not has_prd
            patch["skip_prototype"] = not has_prototype

        return patch
