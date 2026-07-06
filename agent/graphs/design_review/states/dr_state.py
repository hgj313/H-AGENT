"""设计审查图（Design Review Graph）的状态 Schema。"""
from __future__ import annotations

import operator
from typing import Any

from langchain.messages import AnyMessage
from typing_extensions import Annotated, TypedDict


# ---------------------------------------------------------------------------
# Reducers：(current_value, new_value) -> merged_value
# ---------------------------------------------------------------------------
def _merge_dict_overwrite(base: dict | None, upd: dict | None) -> dict:
    """dict 浅合并：upd 覆盖 base 的同名 key，其他保留。

    开发阶段强校验 base/upd 的真实类型，避免 channel 里混入非 dict 值后
    在 dict()/update() 里抛出误导性 ValueError。
    """
    if base is None:
        base = {}
    if upd is None:
        upd = {}
    if not isinstance(base, dict):
        raise TypeError(
            f"node_errors merge: base should be dict, got {type(base)} {base!r}"
        )
    if not isinstance(upd, dict):
        raise TypeError(
            f"node_errors merge: upd should be dict, got {type(upd)} {upd!r}"
        )
    out = dict(base)
    out.update(upd)
    return out


def _sum_int(base: int | None, upd: int | None) -> int:
    """operator.add 的 None-safe 版（base 首次为 None 时不抛 TypeError）。"""
    return (base or 0) + (upd or 0)


def _or_bool(base: bool | None, upd: bool | None) -> bool:
    """任一节点写 True 就保持 True（用于 *_done 标志）。"""
    return bool(base) or bool(upd)


class SpecSource(TypedDict, total=False):
    """单个数据源（PRD / 原型 / 标准）的完整状态。"""
    raw_content: str | list[str] | None
    analysis: Any
    # 形如 {"颜色/主标题颜色": {"value": "#1b2338", "context": "..."}, ...}
    specs: dict[str, dict[str, Any]]
    meta: dict[str, Any]
    is_ready: bool


class DRState(TypedDict, total=False):
    # 流程控制
    # current_node 用 last-writer-wins reducer：允许 fan-in（barrier）与
    # 多个并行分析节点在同一 super-step 并发写，规避 InvalidUpdateError。
    # 多个分支写入时以最后一个 reducer 调用的结果为准（语义仅为可观测的
    # "当前/最近" 节点标记，不参与业务判定）。
    current_node: Annotated[str, lambda _old, new: new]
    # error 字段保留"错误栈顶"语义（last-writer-wins），reducer 保证并发
    # 写入合法；非空 error 优先于空 error，避免被正常路径的空值清空。
    # 用法：上层做等值匹配（见 design_review_graph._route_after_resume）。
    error: Annotated[str | None, lambda old, new: new if new else old]
    # 各节点专项错误：key = 节点名，value = 错误描述。不同节点写不同 key，
    # 用 dict 浅合并 reducer 自然并发安全；barrier 据此决定 *_done 标志。
    node_errors: Annotated[dict[str, str], _merge_dict_overwrite]
    resume: bool

    # 输入
    messages: Annotated[list[AnyMessage], operator.add]
    image_path: list[str] | None
    has_image: bool
    prd_file_path: str | None
    prd_raw_text: str | None

    # 入口校验（llm_react 节点写入）
    input_validated: bool
    skip_prd: bool
    skip_prototype: bool
    standard_queries: list[str]

    # 流程进度（并行场景下必须有 reducer，否则 last-writer-wins 丢值）
    prd_done: Annotated[bool, _or_bool]
    prototype_done: Annotated[bool, _or_bool]
    standard_done: Annotated[bool, _or_bool]
    report_done: Annotated[bool, _or_bool]
    # 节点需返回"新值"语义：state.get("llm_calls", 0) + n
    llm_calls: Annotated[int, _sum_int]
    # 节点只 push 一条 dict，operator.add 自动 append
    llm_call_log: Annotated[list[dict], operator.add]
    plan: Annotated[list[str], operator.add]

    # 细粒度数据（不同 key 互不冲突，dict 引用替换天然安全）
    prd_analysis: SpecSource
    prototype_analysis: SpecSource
    standard_rules: SpecSource
    # 兼容旧字段；若多节点并发写此字段，需改 operator.add
    analysis_result: Annotated[list[dict] | None, lambda base, new: (base or []) + (new or [])]

    # 输出
    report: dict[str, Any] | None


def make_empty_spec_source() -> SpecSource:
    """新建一个空的 SpecSource，供节点初始化使用。"""
    return SpecSource(
        raw_content=None,
        analysis=None,
        specs={},
        meta={},
        is_ready=False,
    )


def get_prd(state: DRState) -> SpecSource:
    return state.get("prd_analysis") or make_empty_spec_source()


def get_prototype(state: DRState) -> SpecSource:
    return state.get("prototype_analysis") or make_empty_spec_source()


def get_standard(state: DRState) -> SpecSource:
    return state.get("standard_rules") or make_empty_spec_source()


def set_current_node(state: dict, node_name: str) -> dict:
    """节点在返回值中调用，统一写入 current_node。"""
    state["current_node"] = node_name
    return state


# 节点依赖图：adj[node] = 该节点完成后才允许跑的下一节点集合
NODE_ORDER: tuple[str, ...] = (
    "llm_react",
    "analyze_prd",
    "retrieve_standard",
    "analyze_prototype",
    "generate_report",
)

DONE_FLAGS: dict[str, str] = {
    "llm_react": "input_validated",
    "analyze_prd": "prd_done",
    "retrieve_standard": "standard_done",
    "analyze_prototype": "prototype_done",
    "generate_report": "report_done",
}

NODE_EDGES: dict[str, set[str]] = {
    "llm_react": {"analyze_prd", "retrieve_standard", "analyze_prototype", "generate_report"},
    "analyze_prd": {"retrieve_standard", "analyze_prototype", "generate_report"},
    "retrieve_standard": {"analyze_prototype", "generate_report"},
    "analyze_prototype": {"generate_report"},
    "generate_report": set(),
}


def downstream_of(node_name: str) -> set[str]:
    """返回 node_name 在 NODE_EDGES 中的所有可达下游（不含自身）。"""
    seen: set[str] = set()
    stack: list[str] = list(NODE_EDGES.get(node_name, set()))
    while stack:
        cur = stack.pop()
        if cur in seen or cur == node_name:
            continue
        seen.add(cur)
        stack.extend(NODE_EDGES.get(cur, set()))
    return seen


SPEC_KEYS: dict[str, str] = {
    "analyze_prd": "prd_analysis",
    "retrieve_standard": "standard_rules",
    "analyze_prototype": "prototype_analysis",
    "generate_report": "report",
}


def _reset_flags(state: dict, nodes: set[str]) -> dict:
    for n in nodes:
        flag = DONE_FLAGS.get(n)
        if flag and flag in state:
            state[flag] = False
        spec_key = SPEC_KEYS.get(n)
        if spec_key and spec_key in state:
            state[spec_key] = None
    return state


def reset_downstream(state: dict, node_name: str) -> dict:
    """把 node_name 及其所有下游节点的 *_done 标志置为 False。

    节点不在 NODE_EDGES 内：no-op；否则自身 + 所有可达下游全部重置。
    """
    if node_name not in NODE_EDGES:
        return state
    targets = downstream_of(node_name) | {node_name}
    return _reset_flags(state, targets)


def reset_from(state: dict, node_name: str) -> dict:
    """reset_downstream 的语义别名。"""
    return reset_downstream(state, node_name)


def reset_invalidated(state: dict, changed_nodes: set[str]) -> dict:
    """对每个 n in changed_nodes 执行 reset_downstream 后取并集。"""
    targets: set[str] = set()
    for n in changed_nodes:
        if n in NODE_EDGES:
            targets |= downstream_of(n) | {n}
    return _reset_flags(state, targets)
