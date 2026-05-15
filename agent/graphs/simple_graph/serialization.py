from __future__ import annotations

from typing import Any

from agent.graphs.simple_graph.models import (
    EdgeDefinition,
    GraphDefinition,
    GraphExecutionState,
    GraphMetadata,
    GraphSnapshot,
    NodeDefinition,
    NodeExecutionRecord,
    NodeKind,
    NodeStatus,
    GraphStatus,
)


def _node_definition_from_dict(payload: dict[str, Any]) -> NodeDefinition:
    return NodeDefinition(
        node_id=payload["node_id"],
        label=payload["label"],
        kind=NodeKind(payload["kind"]),
        depends_on=list(payload.get("depends_on", [])),
        tool_name=payload.get("tool_name"),
        prompt_template=payload.get("prompt_template"),
        input_mapping=dict(payload.get("input_mapping", {})),
        output_key=payload.get("output_key"),
        allow_interrupt=payload.get("allow_interrupt", True),
        metadata=dict(payload.get("metadata", {})),
    )


def graph_definition_from_dict(payload: dict[str, Any]) -> GraphDefinition:
    return GraphDefinition(
        graph_id=payload["graph_id"],
        name=payload["name"],
        version=payload["version"],
        entrypoint=payload["entrypoint"],
        nodes=[_node_definition_from_dict(item) for item in payload["nodes"]],
        edges=[EdgeDefinition(**edge) for edge in payload["edges"]],
        metadata=dict(payload.get("metadata", {})),
    )


def node_record_from_dict(payload: dict[str, Any]) -> NodeExecutionRecord:
    return NodeExecutionRecord(
        node_id=payload["node_id"],
        status=NodeStatus(payload["status"]),
        started_at=payload.get("started_at"),
        ended_at=payload.get("ended_at"),
        attempts=payload.get("attempts", 0),
        inputs=dict(payload.get("inputs", {})),
        output=payload.get("output"),
        error=payload.get("error"),
        stream_chunks=list(payload.get("stream_chunks", [])),
    )


def graph_state_from_dict(payload: dict[str, Any]) -> GraphExecutionState:
    metadata = GraphMetadata(**payload["metadata"])
    definition = graph_definition_from_dict(payload["definition"])
    return GraphExecutionState(
        metadata=metadata,
        definition=definition,
        status=GraphStatus(payload["status"]),
        current_node_id=payload.get("current_node_id"),
        graph_context=dict(payload.get("graph_context", {})),
        node_records={
            node_id: node_record_from_dict(record)
            for node_id, record in payload.get("node_records", {}).items()
        },
        completed_order=list(payload.get("completed_order", [])),
        event_sequence=payload.get("event_sequence", 0),
        snapshot_sequence=payload.get("snapshot_sequence", 0),
        last_error=payload.get("last_error"),
        restored_from_snapshot=payload.get("restored_from_snapshot"),
    )


def snapshot_from_dict(payload: dict[str, Any]) -> GraphSnapshot:
    return GraphSnapshot(
        snapshot_id=payload["snapshot_id"],
        sequence=payload["sequence"],
        reason=payload["reason"],
        created_at=payload["created_at"],
        graph_status=GraphStatus(payload["graph_status"]),
        current_node_id=payload.get("current_node_id"),
        graph_context=dict(payload.get("graph_context", {})),
        node_records={
            node_id: node_record_from_dict(record)
            for node_id, record in payload.get("node_records", {}).items()
        },
        completed_order=list(payload.get("completed_order", [])),
    )
