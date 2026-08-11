"""
DAG 构建器：把"分组并行 + 跨组依赖"描述统一编译为 LangGraph。

支持的描述形式（三种入口）：
1. 分组式：add_parallel_group(graph, "group1", [a, b]) + add_dependency(g, "c", ["group1"])
2. 依赖式：build_from_deps({"c": ["a", "b"], "f": ["d", "e"], "final": ["c", "f", "p"]})
3. LLM 式：parse_with_llm(llm, "a、b 完成后做 c，d、e 完成后做 f，最后汇总 c f p q")

内部统一表示：
    ParallelGroup(name, nodes: list[str], barrier: str | None)
    NodeDeps(node: str, upstream: list[str])

内部生成逻辑：
    - 每个 ParallelGroup 自动插入一个 barrier 节点
    - barrier 节点扇出到下游依赖
    - barrier 节点接收所有组内节点的结果
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
class ParallelGroup:
    """一个并行分组：组内节点并发跑，组跑完才走 barrier。"""
    def __init__(self, name: str, nodes: list[str], barrier: str | None = None):
        self.name = name
        self.nodes = nodes  # 实际业务节点
        self.barrier = barrier or f"{name}__barrier"  # 同步点


class DAGSpec:
    """完整 DAG 描述。"""
    def __init__(
        self,
        nodes: dict[str, Callable],
        groups: list[ParallelGroup],
        # deps: target_node -> [upstream_node_or_group_name]
        deps: dict[str, list[str]],
        entry: str | None = None,
    ):
        self.nodes = nodes
        self.groups = {g.name: g for g in groups}
        self.deps = deps
        self.entry = entry


# ---------------------------------------------------------------------------
# 内部编译：把 DAGSpec 转换成 LangGraph
# ---------------------------------------------------------------------------
def _barrier_node_factory(group: ParallelGroup) -> Callable:
    """生成一个 barrier 节点：不做事，只同步 + 透传状态。"""
    def _barrier(state: dict) -> dict:
        return {"current_node": group.barrier}
    return _barrier


def _resolve_upstream(spec: DAGSpec, target: str) -> list[str]:
    """把 target 的上游依赖（可能是节点名或分组名）展开为具体节点列表。

    - 如果是分组名：返回该组内所有节点 + barrier
    - 如果是节点名：直接返回
    """
    if target in spec.groups:
        return spec.groups[target].nodes + [spec.groups[target].barrier]
    return [target]


def compile_dag(spec: DAGSpec) -> Any:
    """核心编译函数：把 DAGSpec 编译成 LangGraph。"""
    g = StateGraph(dict)  # 这里用 dict 简化，实际用业务 State

    # 1) 添加所有业务节点
    for name, fn in spec.nodes.items():
        g.add_node(name, fn)

    # 2) 为每个分组添加 barrier 节点
    for group in spec.groups.values():
        g.add_node(group.barrier, _barrier_node_factory(group))
        # 组内所有节点 → barrier
        for node in group.nodes:
            g.add_edge(node, group.barrier)

    # 3) 处理 deps：target_node 依赖若干 upstream
    for target, ups in spec.deps.items():
        # 展开所有 upstream 到具体节点
        concrete_ups: set[str] = set()
        for u in ups:
            concrete_ups.update(_resolve_upstream(spec, u))

        if len(concrete_ups) == 1:
            # 单上游：直接连边
            g.add_edge(next(iter(concrete_ups)), target)
        else:
            # 多上游：用 barrier 节点做 fan-in
            fan_in_name = f"{target}__join"
            g.add_node(fan_in_name, lambda state: {"current_node": fan_in_name})
            for u in concrete_ups:
                g.add_edge(u, fan_in_name)
            g.add_edge(fan_in_name, target)

    # 4) 入口
    g.set_entry_point(spec.entry or next(iter(spec.nodes)))

    return g.compile()


# ---------------------------------------------------------------------------
# 入口 1：分组式 API（最常用）
# ---------------------------------------------------------------------------
def add_parallel_group(
    spec: DAGSpec,
    name: str,
    nodes: list[str],
) -> DAGSpec:
    """声明一个并行分组：组内节点并发。"""
    spec.groups[name] = ParallelGroup(name, nodes)
    return spec


def add_dependency(
    spec: DAGSpec,
    target: str,
    upstream: list[str],
) -> DAGSpec:
    """声明 target 节点依赖 upstream（可以是节点名或分组名）。"""
    spec.deps[target] = upstream
    return spec


def build_parallel_dag(
    nodes: dict[str, Callable],
    configure: Callable[[DAGSpec], DAGSpec],
    entry: str | None = None,
) -> Any:
    """DSL 入口：用户写一段 lambda 描述分组和依赖，编译成图。

    Example:
        dag = build_parallel_dag(
            {"a": fa, "b": fb, "c": fc, "d": fd, "e": fe, "f": ff,
             "p": fp, "q": fq, "final": ffinal},
            lambda s: s
            | add_parallel_group("g1", ["a", "b"])
            | add_parallel_group("g2", ["d", "e"])
            | add_dependency("c", ["g1"])
            | add_dependency("f", ["g2"])
            | add_dependency("final", ["c", "f", "p", "q"]),
        )
    """
    spec = DAGSpec(nodes=nodes, groups=[], deps={}, entry=entry)
    spec = configure(spec)
    return compile_dag(spec)


# ---------------------------------------------------------------------------
# 入口 2：依赖式 API（最直接）
# ---------------------------------------------------------------------------
def build_from_deps(
    nodes: dict[str, Callable],
    deps: dict[str, list[str]],
    entry: str | None = None,
) -> Any:
    """直接给依赖 dict，自动推断分组。

    算法：
        - 找到所有 target，把它们归入"按层并行"
        - 同一层（无相互依赖）的节点归为一个 ParallelGroup
        - 入口：依赖图的最上层（无任何上游依赖的节点）
    """
    # 反向：node -> 它被谁依赖
    downstream: dict[str, set[str]] = {n: set() for n in nodes}
    for target, ups in deps.items():
        for u in ups:
            if u in downstream:
                downstream[u].add(target)

    # 找入口节点：deps 里没作为 target 出现，或者上游为空的
    roots = [
        n for n in nodes
        if not deps.get(n) or all(u not in nodes for u in deps.get(n, []))
    ]
    entry = entry or (roots[0] if roots else next(iter(nodes)))

    # 分层：拓扑分层，同层节点归为一个 group
    groups: list[ParallelGroup] = []
    layer_idx: dict[str, int] = {}

    def compute_layer(n: str) -> int:
        if n in layer_idx:
            return layer_idx[n]
        ups = deps.get(n, [])
        if not ups:
            layer_idx[n] = 0
            return 0
        # 上游最大层 + 1
        max_up_layer = 0
        for u in ups:
            if u in nodes:
                max_up_layer = max(max_up_layer, compute_layer(u))
        layer_idx[n] = max_up_layer + 1
        return layer_idx[n]

    for n in nodes:
        compute_layer(n)

    # 按层分组
    by_layer: dict[int, list[str]] = {}
    for n, idx in layer_idx.items():
        by_layer.setdefault(idx, []).append(n)

    # 把 deps 改写成"基于分组"的 deps
    new_deps: dict[str, list[str]] = {}
    for n in nodes:
        ups = deps.get(n, [])
        if ups:
            # 用对应的 group/节点名引用
            new_deps[n] = [f"__layer_{layer_idx[u]}" if u in layer_idx and u != n else u for u in ups]

    # 把所有层注册为 group
    for layer, ns in by_layer.items():
        groups.append(ParallelGroup(f"__layer_{layer}", ns))

    spec = DAGSpec(nodes=nodes, groups=groups, deps=new_deps, entry=entry)
    return compile_dag(spec)


# ---------------------------------------------------------------------------
# 入口 3：LLM 解析式 API
# ---------------------------------------------------------------------------
_LLM_PLAN_PROMPT = """你是一个 DAG 调度规划器。给定任务描述，输出节点依赖关系。

要求：
1. 输出严格的 JSON
2. 格式：{"deps": {"target_node": ["upstream_node_or_group", ...]}}
3. 无依赖的节点不要出现在 deps 里
4. 节点名用小写英文下划线

任务描述：
{task_desc}

可用节点：{available_nodes}

只输出 JSON，不要解释。
"""


def parse_with_llm(
    llm: Any,
    task_desc: str,
    nodes: dict[str, Callable],
) -> Any:
    """让 LLM 分析任务描述，自动生成 deps 并编译。"""
    available = list(nodes.keys())
    prompt = _LLM_PLAN_PROMPT.format(
        task_desc=task_desc,
        available_nodes=available,
    )
    try:
        result = llm.invoke(prompt)
        text = getattr(result, "content", str(result))
        # 抽取 JSON
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("LLM 未返回 JSON")
        parsed = json.loads(m.group(0))
        deps = parsed.get("deps", {})
        return build_from_deps(nodes, deps)
    except Exception as e:
        # fallback：单层无依赖
        return build_from_deps(nodes, {})


# ---------------------------------------------------------------------------
# 入口 3.5：双途径——让人工和 LLM 各自出一版，merge 后用
# ---------------------------------------------------------------------------
def merge_plans(
    human_deps: dict[str, list[str]],
    llm_deps: dict[str, list[str]],
    prefer: str = "human",  # "human" / "llm" / "union" / "intersection"
) -> dict[str, list[str]]:
    """合并人工和 LLM 的依赖描述。

    - prefer="human"：人工的覆盖 LLM（人工是 ground truth）
    - prefer="llm"：LLM 覆盖人工
    - prefer="union"：取并集（更宽松，LLM 找到人工没考虑到的依赖）
    - prefer="intersection"：取交集（更保守，只保留两边都认为需要的依赖）
    """
    if prefer == "human":
        return {**llm_deps, **human_deps}
    if prefer == "llm":
        return {**human_deps, **llm_deps}

    merged: dict[str, list[str]] = {}
    all_keys = set(human_deps) | set(llm_deps)
    for k in all_keys:
        h = set(human_deps.get(k, []))
        l = set(llm_deps.get(k, []))
        if prefer == "union":
            merged[k] = sorted(h | l)
        elif prefer == "intersection":
            merged[k] = sorted(h & l)
    return merged


def build_with_dual_path(
    llm: Any,
    task_desc: str,
    nodes: dict[str, Callable],
    human_deps: dict[str, list[str]] | None = None,
    prefer: str = "human",
) -> Any:
    """双途径构建：人工写一版，LLM 写一版，合并后编译。

    如果 human_deps 为 None，则只走 LLM 路径。
    """
    # LLM 出版
    try:
        result = llm.invoke(_LLM_PLAN_PROMPT.format(
            task_desc=task_desc,
            available_nodes=list(nodes.keys()),
        ))
        text = getattr(result, "content", str(result))
        m = re.search(r"\{.*\}", text, re.S)
        llm_deps = json.loads(m.group(0)).get("deps", {}) if m else {}
    except Exception:
        llm_deps = {}

    if human_deps is None:
        final_deps = llm_deps
    else:
        final_deps = merge_plans(human_deps, llm_deps, prefer=prefer)

    return build_from_deps(nodes, final_deps)
