"""
入口校验节点（llm_react）——图驱动模式。

架构：
- llm_react：检测材料 → LLM 兜底 → 缺失时 interrupt 一次（节点无循环）
- llm_react_resume：处理用户响应 → 更新 state 中的材料字段
- 循环由图的条件边驱动：resume → (材料仍缺) → llm_react → interrupt → resume ...

核心能力：
1. 响应式触发：作为图流程入口，监听 DRState 变更并驱动执行
2. Schema 校验：通过 LlmReactInput schema 统一校验和获取关键输入参数
3. 前端对接：build_state_from_frontend() 支持前端参数 → DRState 构造
4. LLM 兜底：非结构化输入时调用 LLM 从自由文本中提取结构化字段
5. 人机交互：材料缺失时通过 interrupt 机制支持 继续/追加/更改/取消
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from agent.graphs.design_review.schemas.llm_react_schema import LlmReactInput
from agent.graphs.design_review.states.dr_state import DRState

_NODE_NAME = "llm_react"


# ── 辅助函数 ──────────────────────────────────────────────────────────


def _is_human_message(m: Any) -> bool:
    """判断消息是否为 HumanMessage。"""
    role = getattr(m, "type", None) or getattr(m, "role", None)
    return role == "human"


def _extract_single_text(messages: list, idx: int) -> str:
    """从原始 messages 列表中按 index 提取单条消息的文本，无切片拷贝。"""
    content = getattr(messages[idx], "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text", "")
                if t.strip():
                    parts.append(t)
        return "\n".join(parts)
    return ""


def _find_two_human_indices(
    messages: list,
    pos: int,
    found: tuple[int, ...] = (),
) -> tuple[int, ...]:
    """递归辅助函数：从 pos 向前扫描，收集最近两条 HumanMessage 的 index。

    基线条件：
    - found 已有 2 个 index → 返回
    - pos < 0（遍历到列表头）→ 返回已收集的

    操作原始 messages 列表，不创建副本。
    """
    if len(found) >= 2 or pos < 0:
        return found
    if _is_human_message(messages[pos]):
        found = (pos,) + found  # 始终保持 idx_earlier < idx_latest
    return _find_two_human_indices(messages, pos - 1, found)


def _collect_text_from_index(
    messages: list,
    idx: int,
    end: int,
    acc: str = "",
) -> str:
    """递归辅助函数：从 idx 到 end 逐条提取文本并拼接，操作原始列表。"""
    if idx >= end:
        return acc
    text = _extract_single_text(messages, idx)
    sep = "\n" if acc and text else ""
    return _collect_text_from_index(messages, idx + 1, end, acc + sep + text)


#主递归函数
def _extract_text_from_messages(
    messages: list,
    anchor: tuple[int, int] | None = None,
) -> tuple[str, tuple[int, int] | None]:
    """从消息列表中提取当前轮次的用户文本，返回 (text, anchor)。
    anchor 语义：
    - anchor[0]：较早的 HumanMessage index
    - anchor[1]：较晚的 HumanMessage index
    """
    if not messages:
        return "", None

    # 确定扫描起点
    scan_end = len(messages) - 1
    if anchor is not None:
        scan_end = min(anchor[1], scan_end)

    # 递归查找两条 HumanMessage index
    indices = _find_two_human_indices(messages, scan_end)

    if not indices:
        return "", None

    # 从较早的 HumanMessage 开始，提取到列表末尾的全部文本
    start_from = indices[0]
    new_anchor: tuple[int, int] | None = None
    if len(indices) >= 2:
        new_anchor = (indices[0], indices[1])

    text = _collect_text_from_index(messages, start_from, len(messages))
    return text, new_anchor


def _detect_images_in_messages(messages: list) -> list[str]:
    """扫描所有消息，提取 image_url。"""
    urls: list[str] = []
    for m in messages:
        content = getattr(m, "content", "")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "image_url":
                continue
            image_url = item.get("image_url", {})
            if isinstance(image_url, dict):
                url = image_url.get("url", "")
            elif isinstance(image_url, str):
                url = image_url
            else:
                continue
            if url:
                urls.append(url)
    return urls


def _detect_has_prd(state: DRState) -> bool:
    """判断 PRD 材料是否可用。"""
    if state.get("prd_file_path"):
        return True
    if state.get("prd_raw_text"):
        return True
    prd_src = state.get("prd_analysis") or {}
    raw = prd_src.get("raw_content")
    if isinstance(raw, str) and raw.strip():
        return True
    if isinstance(raw, list) and raw:
        return True
    return False


def _detect_has_prototype(state: DRState) -> bool:
    """判断原型图材料是否可用。"""
    if state.get("image_path"):
        return True
    return False


def _detect_materials(state: DRState) -> tuple[bool, bool, list[str], list[str]]:
    """检测材料可用性，返回 (has_prd, has_prototype, image_path, missing)。"""
    image_path = list(state.get("image_path") or [])
    messages = state.get("messages") or []
    msg_images = _detect_images_in_messages(messages)
    if msg_images and not image_path:
        image_path = msg_images

    has_prd = _detect_has_prd(state)
    has_prototype = bool(image_path)

    missing: list[str] = []
    if not has_prototype:
        missing.append("原型图")
    if not has_prd:
        missing.append("PRD 文档")

    return has_prd, has_prototype, image_path, missing


# ── 前端参数 → DRState 构造 ──────────────────────────────────────────


def build_state_from_frontend(
    params: dict[str, Any] | LlmReactInput,
    messages: list | None = None,
) -> dict[str, Any]:
    """将前端传入的参数构造为合法的 DRState 初始片段。

    支持两种入参形式：
    - dict：直接传入原始参数字典（前端 JSON 解析结果）
    - LlmReactInput：已经过 schema 校验的 Pydantic 模型

    返回值可直接作为 graph.invoke(input=...) 的 input 参数。

    用法示例::

        # 字符串会自动包装为 HumanMessage
        state_input = build_state_from_frontend(
            {"prd_file_path": "/docs/prd.pdf", "image_path": ["https://..."]},
            messages=["请审查这个设计"],
        )
        result = graph.invoke(state_input)
    """
    if isinstance(params, dict):
        validated = LlmReactInput.model_validate(params)
    elif isinstance(params, LlmReactInput):
        validated = params
    else:
        raise TypeError(f"params 必须是 dict 或 LlmReactInput，收到 {type(params)}")

    state: dict[str, Any] = {}

    if validated.prd_file_path:
        state["prd_file_path"] = validated.prd_file_path
    if validated.prd_raw_text:
        state["prd_raw_text"] = validated.prd_raw_text
    if validated.image_path:
        state["image_path"] = validated.image_path
    if validated.standard_queries:
        state["standard_queries"] = validated.standard_queries

    if messages:
        wrapped: list = []
        for m in messages:
            if isinstance(m, str):
                wrapped.append(HumanMessage(content=m))
            else:
                wrapped.append(m)
        state["messages"] = wrapped

    return state


# ── LLM 兜底提取 ─────────────────────────────────────────────────────


def _extract_structured_via_llm(
    llm: Any,
    unstructured_text: str,
) -> LlmReactInput | None:
    """当输入为非结构化内容时，调用 LLM 从中提取符合 schema 的结构化信息。

    使用 bind_tools([LlmReactInput], tool_choice="required", strict=True)
    强制模型按 schema 结构返回，与 generate_comparative_report 同一模式。
    """
    prompt = (
        "你是一个输入解析器。用户会给你一段自由文本，可能包含以下信息：\n"
        "- PRD 文档的文件路径或文本内容\n"
        "- 原型图的图片地址\n"
        "- 设计标准检索关键词\n"
        "- 用户意图说明（如'只看PRD'、'跳过原型分析'等）\n\n"
        "请从文本中提取这些信息，调用 LlmReactInput 工具返回结构化结果。\n"
        "如果某项信息在文本中不存在，对应字段留 null。\n\n"
        f"用户输入：\n{unstructured_text}"
    )

    try:
        bound_model = llm.bind_tools(
            [LlmReactInput],
            tool_choice="required",
            strict=True,
            parallel_tool_calls=False,
        )
        ai_message = bound_model.invoke(prompt)

        tool_calls = getattr(ai_message, "tool_calls", None) or []
        for tc in tool_calls:
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
            if isinstance(args, dict):
                return LlmReactInput.model_validate(args)
    except Exception:
        pass
    return None


# ── 节点 1：检测 + interrupt ──────────────────────────────────────────


class LlmReactNode:
    """入口校验节点：检测材料可用性，缺失时 interrupt 一次。

    不含循环——循环由图的条件边驱动：
        llm_react → llm_react_resume → (材料仍缺) → llm_react

    流程：
    1. 幂等检查：已校验则直接透传
    2. LLM 兜底：非结构化输入 → 结构化提取
    3. 材料检测：两者齐全 → 直接通过
    4. 材料缺失 → interrupt 一次，等待用户响应
       （用户响应由 llm_react_resume 节点处理，不在本节点内）
    """

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm

    @staticmethod
    def _is_trusted(state: DRState) -> bool:
        return bool(state.get("input_validated"))

    def _try_llm_extraction(self, state: DRState) -> dict[str, Any] | None:
        """非结构化输入时调用 LLM 提取缺失字段，返回 patch dict 或 None。"""
        if not self.llm:
            return None

        messages = state.get("messages") or []
        raw_text, _anchor = _extract_text_from_messages(messages)
        if not raw_text or len(raw_text.strip()) < 10:
            return None

        if _detect_has_prd(state) and _detect_has_prototype(state):
            return None

        extracted = _extract_structured_via_llm(self.llm, raw_text)
        if not extracted:
            return None

        patch: dict[str, Any] = {}
        if extracted.prd_file_path and not state.get("prd_file_path"):
            patch["prd_file_path"] = extracted.prd_file_path
        if extracted.prd_raw_text and not state.get("prd_raw_text"):
            patch["prd_raw_text"] = extracted.prd_raw_text
        if extracted.image_path and not state.get("image_path"):
            patch["image_path"] = extracted.image_path
        if extracted.standard_queries and not state.get("standard_queries"):
            patch["standard_queries"] = extracted.standard_queries
        if extracted.user_intent:
            patch["user_intent"] = extracted.user_intent

        return patch if patch else None

    def __call__(self, state: DRState) -> dict:
        # 幂等
        if self._is_trusted(state):
            return {"current_node": _NODE_NAME, "input_validated": True}

        # LLM 兜底
        llm_patch = self._try_llm_extraction(state)
        llm_calls = 0
        if llm_patch:
            state = {**state, **llm_patch}
            llm_calls = 1

        # 材料检测
        has_prd, has_prototype, image_path, missing = _detect_materials(state)

        # 齐全 → 通过
        if has_prd and has_prototype:
            return {
                "current_node": _NODE_NAME,
                "image_path": image_path,
                "input_validated": True,
                "llm_calls": llm_calls,
            }

        # 缺失 → interrupt 一次（不在节点内循环）
        available_desc = []
        if has_prototype:
            available_desc.append("原型图")
        if has_prd:
            available_desc.append("PRD 文档")
        available_text = "、".join(available_desc) if available_desc else "无"
        missing_text = "、".join(missing)

        question = (
            f"当前已提供：{available_text}；缺少：{missing_text}。\n请问如何处理？"
            if available_desc
            else "未检测到任何审查材料（原型图和PRD文档均缺失），请上传相关材料。"
        )

        # interrupt 暂停，用户响应由 llm_react_resume 处理
        interrupt({
            "current_node": _NODE_NAME,
            "question": question,
            "available": available_text,
            "missing": missing_text,
            "has_prd": has_prd,
            "has_prototype": has_prototype,
            "options": ["继续", "追加", "更改", "取消"],
        })

        # interrupt 恢复后：写入当前材料状态，由图条件边决定下一步
        return {
            "current_node": _NODE_NAME,
            "image_path": image_path,
            "prd_file_path": state.get("prd_file_path"),
            "prd_raw_text": state.get("prd_raw_text"),
            "llm_calls": llm_calls,
        }


