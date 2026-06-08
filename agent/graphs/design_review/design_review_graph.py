"""
设计审查图（Design Review Graph）主入口。

对外暴露三个 CompiledStateGraph：
- create_design_review_graph(llm)：主流程业务编排图
- create_assistant_subgraph(llm)：ReAct 助手子图
- create_top_level_graph(llm)：顶层路由图（main ⇄ assistant）

主流程与助手子图共享同一份 DRState，使助手子图对主图产物只读可见。
"""
from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent.graphs.design_review.states.dr_state import DRState
from agent.graphs.design_review.tools.read_file.read_file import read_file_tool
from agent.graphs.design_review.tools.analyze_prototype.analyze_prototype import (
    analyze_prototype,
)

try:
    from agent.graphs.design_review.nodes.llm_react_node import (
        LlmReactNode,
        build_state_from_frontend,
    )
except Exception:
    LlmReactNode = None  # type: ignore
    build_state_from_frontend = None  # type: ignore
try:
    from agent.graphs.design_review.nodes.llm_react_resume_node import (
        LlmReactResumeNode,
    )
except Exception:
    LlmReactResumeNode = None  # type: ignore
try:
    from agent.graphs.design_review.nodes.analyze_prd_node import AnalyzePRDNode
except Exception:
    AnalyzePRDNode = None  # type: ignore
try:
    from agent.graphs.design_review.nodes.retrieve_standard_node import (
        RetrieveStandardNode,
    )
except Exception:
    RetrieveStandardNode = None  # type: ignore
try:
    from agent.graphs.design_review.nodes.analyze_prototype_node import (
        AnalyzePrototypeNode,
    )
except Exception:
    AnalyzePrototypeNode = None  # type: ignore
try:
    from agent.graphs.design_review.nodes.generate_comparative_report_node import (
        GenerateComparativeReportNode,
    )
except Exception:
    GenerateComparativeReportNode = None  # type: ignore
try:
    from agent.graphs.design_review.nodes.planner_node import PlannerNode
except Exception:
    PlannerNode = None  # type: ignore


# ── 路由函数 ──────────────────────────────────────────────────────────


def _route_after_llm_react(state: DRState) -> str:
    """llm_react 完成后的路由（图驱动循环）：
    - 校验通过 → planner
    - 有待处理的用户响应 → llm_react_resume
    - 其他（无材料、未校验）→ END
    """
    if state.get("_resume_data"):  # type: ignore[typeddict-item]
        return "llm_react_resume"
    if state.get("input_validated"):
        return "planner"
    return END


def _route_after_resume(state: DRState) -> str:
    """llm_react_resume 完成后的路由：
    - 校验通过 → planner
    - 用户取消 → END
    - 材料已更新但仍缺 → 回到 llm_react 重新检测
    """
    if state.get("input_validated"):
        return "planner"
    if state.get("error") == "user_cancelled":
        return END
    return "llm_react"


def _route_after_prd(state: DRState) -> str:
    """analyze_prd 完成后回到 barrier，由 planner 决定下一步。"""
    return "barrier"


def _route_after_standard(state: DRState) -> str:
    return "barrier"


def _route_after_prototype(state: DRState) -> str:
    return "barrier"


def _barrier_should_continue(state: DRState) -> str:
    """barrier 节点：所有分析节点都 done 后才放行到 generate_report。

    这里是 fan-in 的真正实现——只要还有任一分析节点没完成，就回到 planner
    让其重新派发剩余节点。

    失败标志位（done=True）的注入由 `barrier_node` 完成，本函数只读 state 决定路由。
    """
    if (
        state.get("prd_done")
        and state.get("standard_done")
        and state.get("prototype_done")
    ):
        return "generate_report"
    return "planner"


def _collect_failed_done_flags(state: DRState) -> dict[str, bool]:
    """扫一遍三个 analysis 节点产物：若 is_ready=False 且含 error，则把对应 done
    标志设为 True，避免 planner 无限重试。

    优先依据 node_errors[<node>] 判断，兜底兼容旧的 SpecSource.analysis.error。
    返回值是 barrier_node 要合并到 state 的增量 dict。
    """
    node_errors: dict[str, str] = state.get("node_errors") or {}
    updates: dict[str, bool] = {}
    for node_key, src_key, done_key in (
        ("analyze_prd", "prd_analysis", "prd_done"),
        ("retrieve_standard", "standard_rules", "standard_done"),
        ("analyze_prototype", "prototype_analysis", "prototype_done"),
    ):
        done_val = state.get(done_key)
        if done_val:
            continue

        # 优先：node_errors 是否已记录该节点的专项错误
        if node_key in node_errors:
            updates[done_key] = True
            continue

        # 兜底：SpecSource.analysis.error（兼容旧字段）
        src = state.get(src_key) or {}
        if not isinstance(src, dict):
            continue
        analysis = src.get("analysis")
        if (
            src.get("is_ready") is False
            and isinstance(analysis, dict)
            and "error" in analysis
        ):
            updates[done_key] = True
    return updates


def _route_from_planner(state: DRState) -> list[str]:
    """从 planner 拿到的 plan 扇出到对应节点。

    - plan 是 list：LangGraph 自动 fan-out 并行执行
    - plan 只含 generate_report：直接走报告
    - plan 为空：兜底走 END
    """
    plan = state.get("plan") or []
    if not plan:
        return END
    # 校验 plan 里的节点名必须存在
    valid = {"analyze_prd", "retrieve_standard", "analyze_prototype", "generate_report"}
    targets = [n for n in plan if n in valid]
    return targets if targets else END


# ── 图构建 ──────────────────────────────────────────────────────────


def create_design_review_graph(llm: Any):
    graph = StateGraph(DRState)

    if LlmReactNode is None:
        raise RuntimeError("LlmReactNode 不可用")
    if LlmReactResumeNode is None:
        raise RuntimeError("LlmReactResumeNode 不可用")
    if AnalyzePRDNode is None:
        raise RuntimeError("AnalyzePRDNode 不可用")
    if RetrieveStandardNode is None:
        raise RuntimeError("RetrieveStandardNode 不可用")
    if AnalyzePrototypeNode is None:
        raise RuntimeError("AnalyzePrototypeNode 不可用")
    if GenerateComparativeReportNode is None:
        raise RuntimeError("GenerateComparativeReportNode 不可用")
    if PlannerNode is None:
        raise RuntimeError("PlannerNode 不可用")

    # 注册节点
    graph.add_node("llm_react", LlmReactNode(llm=llm))
    graph.add_node("llm_react_resume", LlmReactResumeNode())
    graph.add_node("planner", PlannerNode(llm=llm))
    graph.add_node("analyze_prd", AnalyzePRDNode())
    graph.add_node("retrieve_standard", RetrieveStandardNode())
    graph.add_node("analyze_prototype", AnalyzePrototypeNode())
    graph.add_node("generate_report", GenerateComparativeReportNode())

    def barrier_node(state: DRState) -> dict:
        # 失败注入：分析节点因缺输入/工具异常已写入 error，视为 done（拿部分数据继续）
        failed_done = _collect_failed_done_flags(state)
        return {"current_node": "barrier", **failed_done}

    graph.add_node("barrier", barrier_node)

    # 入口：START → llm_react
    graph.set_entry_point("llm_react")

    # llm_react → planner（校验通过）/ llm_react_resume（有用户响应）/ END
    graph.add_conditional_edges(
        "llm_react",
        _route_after_llm_react,
        {"planner": "planner", "llm_react_resume": "llm_react_resume", END: END},
    )

    # llm_react_resume → planner（通过）/ llm_react（重新检测）/ END（取消）
    graph.add_conditional_edges(
        "llm_react_resume",
        _route_after_resume,
        {"planner": "planner", "llm_react": "llm_react", END: END},
    )

    # planner 扇出：返回 list 触发并行
    graph.add_conditional_edges(
        "planner",
        _route_from_planner,
        {
            "analyze_prd": "analyze_prd",
            "retrieve_standard": "retrieve_standard",
            "analyze_prototype": "analyze_prototype",
            "generate_report": "generate_report",
            END: END,
        },
    )

    # 三个分析节点跑完后都进 barrier 判断
    for node, router in (
        ("analyze_prd", _route_after_prd),
        ("retrieve_standard", _route_after_standard),
        ("analyze_prototype", _route_after_prototype),
    ):
        graph.add_conditional_edges(
            node,
            router,
            {"barrier": "barrier"},
        )

    # barrier 决策：都 done 就生成报告，否则回 planner 继续派发
    graph.add_conditional_edges(
        "barrier",
        _barrier_should_continue,
        {"generate_report": "generate_report", "planner": "planner"},
    )

    graph.add_edge("generate_report", END)

    return graph.compile()


# ── 助手子图 ──────────────────────────────────────────────────────────


def create_assistant_subgraph(llm: Any):
    sub = StateGraph(DRState)
    tool_node = ToolNode(
        [read_file_tool, analyze_prototype],
        handle_tool_errors=True,
    )

    def assistant_llm(state: DRState) -> dict:
        llm_with_tools = llm.bind_tools([read_file_tool, analyze_prototype])
        result = llm_with_tools.invoke(state["messages"])
        return {
            "current_node": "assistant_llm",
            "messages": [result],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    sub.add_node("assistant_llm", assistant_llm)
    sub.add_node("tools", tool_node)
    sub.set_entry_point("assistant_llm")
    sub.add_conditional_edges(
        "assistant_llm",
        _assistant_should_continue,
        {"tools": "tools", "end": END},
    )
    sub.add_edge("tools", "assistant_llm")
    return sub.compile()


def _assistant_should_continue(state: DRState) -> str:
    last_msg = state["messages"][-1] if state.get("messages") else None
    if last_msg and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "end"


# ── 顶层路由图 ────────────────────────────────────────────────────────


def _route_top_level(state: DRState) -> Literal["main", "assistant"]:
    in_main_flow = (
        not state.get("report_done", False)
        and (
            state.get("image_path")
            or state.get("prd_file_path")
            or state.get("prd_raw_text")
        )
    )
    return "main" if in_main_flow else "assistant"


def create_top_level_graph(llm: Any):
    main_g = create_design_review_graph(llm)
    assistant_g = create_assistant_subgraph(llm)

    top = StateGraph(DRState)
    top.add_node("main", main_g)
    top.add_node("assistant", assistant_g)
    top.add_conditional_edges(
        START,
        _route_top_level,
        {"main": "main", "assistant": "assistant"},
    )
    top.add_edge("main", END)
    top.add_edge("assistant", END)
    return top.compile()


__all__ = [
    "create_design_review_graph",
    "create_assistant_subgraph",
    "create_top_level_graph",
    "build_state_from_frontend",
    "DRState",
]
