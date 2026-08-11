"""
规划器节点：
- 基于规则 + 可选 LLM 增强，决定本次执行需要跑哪些分析节点
- 输出 plan: list[str] （节点名集合，写入 state.plan）
- 不修改业务数据，只做调度决策
"""
from __future__ import annotations

from typing import Any

from agent.graphs.design_review.schemas.planner_schema import PlannerDecision
from agent.graphs.design_review.states.dr_state import DRState


_NODE_NAME = "planner"

# 节点名 -> 触发该节点所需的最小输入字段（任一即可）
_NODE_INPUT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "analyze_prd": ("prd_file_path", "prd_raw_text"),  # 任一即可
    "retrieve_standard": (),  # 标准检索总是可以跑（内部会决定查什么）
    "analyze_prototype": ("image_path",),
}

_VALID_NODES = {"analyze_prd", "retrieve_standard", "analyze_prototype", "generate_report"}


def _rule_based_plan(state: DRState) -> list[str]:
    """规则规划：基于已 done 标志 + 输入可用性决定执行集合。"""
    plan: list[str] = []
    for node_name, required in _NODE_INPUT_REQUIREMENTS.items():
        # 跳过用户已确认跳过的节点
        if node_name == "analyze_prd" and state.get("skip_prd"):
            continue
        if node_name == "analyze_prototype" and state.get("skip_prototype"):
            continue

        done_flag = {
            "analyze_prd": "prd_done",
            "retrieve_standard": "standard_done",
            "analyze_prototype": "prototype_done",
        }.get(node_name, "")
        if state.get(done_flag):
            continue
        # 检查输入是否就绪（analyze_prd 只需任一字段即可）
        if node_name == "analyze_prd":
            inputs_ok = any(state.get(field) for field in required) if required else True
        else:
            inputs_ok = all(state.get(field) for field in required) if required else True
        if inputs_ok:
            plan.append(node_name)
    return plan


def _llm_enhanced_plan(llm: Any, state: DRState, base_plan: list[str]) -> list[str]:
    """LLM 增强规划：仅在用户消息里出现"先看 XX" / "跳过 XX"等意图时调用。

    绝大多数情况下不调用，节省成本。
    """
    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        content = getattr(m, "content", "")
        if isinstance(content, str) and content.strip():
            last_user_msg = content
            break
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    last_user_msg = item.get("text", "")
                    break
        if last_user_msg:
            break

    # 触发 LLM 规划的关键词（可按需扩展）
    intent_keywords = ["只要", "先", "跳过", "不", "only", "skip", "先看", "暂不"]
    if not any(kw in last_user_msg for kw in intent_keywords):
        return base_plan

    user_prompt = f"""你是一个设计审查任务的规划器。
根据用户最新消息和当前状态，决定需要执行哪些分析节点。

可选节点：analyze_prd, retrieve_standard, analyze_prototype, generate_report

当前 base_plan: {base_plan}
已完成节点: prd_done={state.get("prd_done")}, standard_done={state.get("standard_done")}, prototype_done={state.get("prototype_done")}, report_done={state.get("report_done")}
可用输入: image_path={bool(state.get("image_path"))}, prd_file_path={bool(state.get("prd_file_path"))}, prd_raw_text={bool(state.get("prd_raw_text"))}
用户最新消息: {last_user_msg}

请调用 PlannerDecision 工具返回最终 plan。
"""

    try:
        bound_model = llm.bind_tools(
            [PlannerDecision],
            tool_choice="required",
            strict=True,
            parallel_tool_calls=False,
        )
        ai_message = bound_model.invoke(user_prompt)

        tool_calls = getattr(ai_message, "tool_calls", None) or []
        for tc in tool_calls:
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
            if isinstance(args, dict) and "plan" in args:
                plan = [n for n in args["plan"] if n in _VALID_NODES]
                if plan:
                    return plan
    except Exception:
        pass
    return base_plan


class PlannerNode:
    """规划器：决策本次要跑哪些节点。

    模式：
        - 纯规则（llm=None）：确定性、零成本
        - 规则 + LLM 增强（llm 给定）：处理用户显式意图
    """

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm

    def __call__(self, state: DRState) -> dict:
        base = _rule_based_plan(state)
        plan = _llm_enhanced_plan(self.llm, state, base) if self.llm else base

        # 如果 plan 为空但所有 done 都是 True，直接跳到 report
        if not plan and all(
            state.get(f)
            for f in ("prd_done", "standard_done", "prototype_done")
        ):
            plan = ["generate_report"]

        return {
            "current_node": _NODE_NAME,
            "plan": plan,
            # 节点返回"增量"：reducer _sum_int 会累加到 state.llm_calls
            "llm_calls": 1 if self.llm and plan != base else 0,
        }
