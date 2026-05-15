from __future__ import annotations

from collections import defaultdict, deque

from agent.graphs.simple_graph.models import GraphDefinition


class GraphValidationError(ValueError):
    pass


def validate_graph_definition(definition: GraphDefinition) -> list[str]:
    node_map = {node.node_id: node for node in definition.nodes}
    if definition.entrypoint not in node_map:
        raise GraphValidationError(f"入口节点不存在: {definition.entrypoint}")

    if len(node_map) != len(definition.nodes):
        raise GraphValidationError("节点 ID 必须唯一")

    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {node_id: 0 for node_id in node_map}

    for edge in definition.edges:
        if edge.source not in node_map or edge.target not in node_map:
            raise GraphValidationError(f"边引用了不存在的节点: {edge.source} -> {edge.target}")
        adjacency[edge.source].append(edge.target)
        indegree[edge.target] += 1

    for node in definition.nodes:
        for dependency in node.depends_on:
            if dependency not in node_map:
                raise GraphValidationError(f"节点 {node.node_id} 依赖不存在的节点 {dependency}")
            if node.node_id not in adjacency.get(dependency, []):
                raise GraphValidationError(
                    f"节点 {node.node_id} 的依赖 {dependency} 未在边定义中体现"
                )

    topo_order = _topological_sort(indegree, adjacency)
    if len(topo_order) != len(definition.nodes):
        raise GraphValidationError("图存在循环依赖，无法完成拓扑排序")

    for node in definition.nodes:
        node_index = topo_order.index(node.node_id)
        for dependency in node.depends_on:
            if topo_order.index(dependency) > node_index:
                raise GraphValidationError(f"节点 {node.node_id} 依赖顺序非法: {dependency}")

    return topo_order


def _topological_sort(indegree: dict[str, int], adjacency: dict[str, list[str]]) -> list[str]:
    indegree_copy = dict(indegree)
    queue = deque([node_id for node_id, degree in indegree_copy.items() if degree == 0])
    ordered: list[str] = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for neighbor in adjacency.get(current, []):
            indegree_copy[neighbor] -= 1
            if indegree_copy[neighbor] == 0:
                queue.append(neighbor)
    return ordered
