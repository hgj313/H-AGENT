from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class NodeKind(StrEnum):
    INPUT = "input"
    TOOL = "tool"
    REASONING = "reasoning"


class NodeStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class GraphStatus(StrEnum):
    CREATED = "created"
    VALIDATED = "validated"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    RESTORED = "restored"


class InterruptAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    UPDATE_INPUTS = "update_inputs"
    JUMP_TO_NODE = "jump_to_node"
    ROLLBACK_TO_SNAPSHOT = "rollback_to_snapshot"


@dataclass(slots=True)
class EdgeDefinition:
    source: str
    target: str


@dataclass(slots=True)
class NodeDefinition:
    node_id: str
    label: str
    kind: NodeKind
    depends_on: list[str] = field(default_factory=list)
    tool_name: str | None = None
    prompt_template: str | None = None
    input_mapping: dict[str, Any] = field(default_factory=dict)
    output_key: str | None = None
    allow_interrupt: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphDefinition:
    graph_id: str
    name: str
    version: str
    entrypoint: str
    nodes: list[NodeDefinition]
    edges: list[EdgeDefinition]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NodeExecutionRecord:
    node_id: str
    status: NodeStatus = NodeStatus.PENDING
    started_at: str | None = None
    ended_at: str | None = None
    attempts: int = 0
    inputs: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str | None = None
    stream_chunks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GraphMetadata:
    graph_id: str
    graph_name: str
    graph_version: str
    user_id: str
    session_id: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class GraphSnapshot:
    snapshot_id: str
    sequence: int
    reason: str
    created_at: str
    graph_status: GraphStatus
    current_node_id: str | None
    graph_context: dict[str, Any]
    node_records: dict[str, NodeExecutionRecord]
    completed_order: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GraphExecutionState:
    metadata: GraphMetadata
    definition: GraphDefinition
    status: GraphStatus = GraphStatus.CREATED
    current_node_id: str | None = None
    graph_context: dict[str, Any] = field(default_factory=dict)
    node_records: dict[str, NodeExecutionRecord] = field(default_factory=dict)
    completed_order: list[str] = field(default_factory=list)
    event_sequence: int = 0
    snapshot_sequence: int = 0
    last_error: str | None = None
    restored_from_snapshot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload
