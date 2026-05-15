from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import Any

from agent.graphs.simple_graph.events import GraphEvent
from agent.graphs.simple_graph.models import (
    GraphExecutionState,
    GraphMetadata,
    GraphSnapshot,
    GraphStatus,
    InterruptAction,
    NodeDefinition,
    NodeExecutionRecord,
    NodeKind,
    NodeStatus,
    utc_now,
)
from agent.graphs.simple_graph.runtime.interrupts import InterruptCommand, InterruptController
from agent.graphs.simple_graph.models import GraphDefinition
from agent.graphs.simple_graph.serialization import graph_state_from_dict, snapshot_from_dict
from agent.graphs.simple_graph.storage.file_store import FileSystemGraphStore
from agent.graphs.simple_graph.tool_registry import get_tool
from agent.graphs.simple_graph.validator import validate_graph_definition
from llm_model.reasoning_model.minimax import minimax_reasoning_model


class GraphExecutor:
    def __init__(self, store: FileSystemGraphStore, model: minimax_reasoning_model | None = None) -> None:
        self.store = store
        self.model = model or minimax_reasoning_model(provider="anthropic", enable_mock=True)

    def create_state(
        self,
        user_id: str,
        session_id: str,
        definition: GraphDefinition,
        request_payload: dict[str, Any],
    ) -> GraphExecutionState:
        topo_order = validate_graph_definition(definition)
        state = GraphExecutionState(
            metadata=GraphMetadata(
                graph_id=definition.graph_id,
                graph_name=definition.name,
                graph_version=definition.version,
                user_id=user_id,
                session_id=session_id,
            ),
            definition=definition,
            status=GraphStatus.VALIDATED,
            graph_context={"request": request_payload, "topology": topo_order},
            node_records={
                node.node_id: NodeExecutionRecord(
                    node_id=node.node_id,
                    status=NodeStatus.READY if node.node_id == definition.entrypoint else NodeStatus.PENDING,
                )
                for node in definition.nodes
            },
        )
        self._persist_state(state, "state_created")
        return state

    def load_state(self, user_id: str, session_id: str, requester_user_id: str | None = None) -> GraphExecutionState:
        self.store.validate_scope(requester_user_id or user_id, user_id)
        payload = self.store.load_state(user_id, session_id)
        return graph_state_from_dict(payload)

    def restore_from_snapshot(
        self,
        user_id: str,
        session_id: str,
        snapshot_id: str,
        requester_user_id: str | None = None,
    ) -> GraphExecutionState:
        self.store.validate_scope(requester_user_id or user_id, user_id)
        snapshot_payload = self.store.load_snapshot(user_id, session_id, snapshot_id)
        state = self.load_state(user_id, session_id, requester_user_id=requester_user_id)
        snapshot = snapshot_from_dict(snapshot_payload)
        state.status = GraphStatus.RESTORED
        state.current_node_id = snapshot.current_node_id
        state.graph_context = dict(snapshot.graph_context)
        state.node_records = dict(snapshot.node_records)
        state.restored_from_snapshot = snapshot.snapshot_id
        self._persist_state(state, "state_restored")
        return state

    def execute(self, state: GraphExecutionState, controller: InterruptController) -> GraphExecutionState:
        topology = list(state.graph_context["topology"])
        definition_map = {node.node_id: node for node in state.definition.nodes}
        state.status = GraphStatus.RUNNING
        self._emit(state, "graph_started", payload={"topology": topology})
        self._snapshot(state, "graph_started")

        for node_id in topology:
            record = state.node_records[node_id]
            if record.status == NodeStatus.COMPLETED:
                continue
            node = definition_map[node_id]
            self._handle_interrupts(state, controller)
            self._wait_until_resumed(state, controller)
            self._ensure_dependencies_completed(state, node)
            self._run_node(state, node, controller)
            if state.status == GraphStatus.FAILED:
                break

        if state.status != GraphStatus.FAILED:
            state.status = GraphStatus.COMPLETED
            self._emit(state, "graph_completed", payload={"completed_order": state.completed_order})
            self._snapshot(state, "graph_completed")
        self._persist_state(state, "graph_finished")
        return state

    def replay(self, user_id: str, session_id: str, requester_user_id: str | None = None) -> list[dict[str, Any]]:
        self.store.validate_scope(requester_user_id or user_id, user_id)
        return self.store.load_events(user_id, session_id)

    def list_snapshots(self, user_id: str, session_id: str, requester_user_id: str | None = None) -> list[str]:
        self.store.validate_scope(requester_user_id or user_id, user_id)
        return [path.stem.split("_", 1)[1] for path in self.store.list_snapshots(user_id, session_id)]

    def _run_node(
        self,
        state: GraphExecutionState,
        node: NodeDefinition,
        controller: InterruptController,
    ) -> None:
        record = state.node_records[node.node_id]
        record.status = NodeStatus.RUNNING
        record.started_at = utc_now()
        record.attempts += 1
        state.current_node_id = node.node_id
        self._emit(state, "node_started", node.node_id, payload={"kind": node.kind})
        self._snapshot(state, f"node_started:{node.node_id}")

        try:
            resolved_inputs = self._resolve_inputs(state, node)
            record.inputs = resolved_inputs
            if node.kind == NodeKind.INPUT:
                output = dict(state.graph_context["request"])
            elif node.kind == NodeKind.TOOL:
                output = self._execute_tool_node(state, node, resolved_inputs)
            elif node.kind == NodeKind.REASONING:
                output = self._execute_reasoning_node(state, node, resolved_inputs, controller)
            else:
                raise ValueError(f"未知节点类型: {node.kind}")

            record.output = output
            if node.output_key:
                state.graph_context[node.output_key] = output
            state.graph_context[node.node_id] = output
            record.status = NodeStatus.COMPLETED
            record.ended_at = utc_now()
            state.completed_order.append(node.node_id)
            self._emit(
                state,
                "node_completed",
                node.node_id,
                payload={"output": output, "context_keys": sorted(state.graph_context.keys())},
            )
            self._snapshot(state, f"node_completed:{node.node_id}")
            self._refresh_ready_nodes(state)
            self._persist_state(state, "node_completed")
        except Exception as exc:  # noqa: BLE001
            record.status = NodeStatus.FAILED
            record.error = str(exc)
            record.ended_at = utc_now()
            state.status = GraphStatus.FAILED
            state.last_error = str(exc)
            self._emit(state, "node_failed", node.node_id, payload={"error": str(exc)})
            self._snapshot(state, f"node_failed:{node.node_id}")
            self._persist_state(state, "node_failed")

    def _execute_tool_node(self, state: GraphExecutionState, node: NodeDefinition, inputs: dict[str, Any]) -> Any:
        tool = get_tool(node.tool_name or "")
        self._emit(
            state,
            "tool_invoked",
            node.node_id,
            payload={"tool_name": tool.name, "inputs": inputs},
        )
        result = tool.invoke(**inputs)
        self._emit(
            state,
            "tool_completed",
            node.node_id,
            payload={"tool_name": tool.name, "result": result},
        )
        return result

    def _execute_reasoning_node(
        self,
        state: GraphExecutionState,
        node: NodeDefinition,
        inputs: dict[str, Any],
        controller: InterruptController,
    ) -> str:
        prompt = (node.prompt_template or "").format(**inputs)
        chunks: list[str] = []
        for chunk in self.model.stream_reasoning(prompt=prompt, context=inputs):
            self._handle_interrupts(state, controller)
            self._wait_until_resumed(state, controller)
            chunks.append(chunk)
            state.node_records[node.node_id].stream_chunks.append(chunk)
            self._emit(
                state,
                "reasoning_chunk",
                node.node_id,
                payload={"chunk": chunk, "aggregated": "".join(chunks)},
            )
            self._persist_state(state, "reasoning_chunk")
            time.sleep(0.01)
        return "".join(chunks)

    def _resolve_inputs(self, state: GraphExecutionState, node: NodeDefinition) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        if not node.input_mapping:
            return resolved
        for input_name, source in node.input_mapping.items():
            resolved[input_name] = self._lookup_context_value(state.graph_context, source)
        return resolved

    def _lookup_context_value(self, graph_context: dict[str, Any], path: str) -> Any:
        if path in graph_context:
            return graph_context[path]
        current: Any = graph_context
        for segment in path.split("."):
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            else:
                raise KeyError(f"无法解析输入映射: {path}")
        return current

    def _refresh_ready_nodes(self, state: GraphExecutionState) -> None:
        for node in state.definition.nodes:
            record = state.node_records[node.node_id]
            if record.status != NodeStatus.PENDING:
                continue
            if all(
                state.node_records[dependency].status == NodeStatus.COMPLETED
                for dependency in node.depends_on
            ):
                record.status = NodeStatus.READY

    def _ensure_dependencies_completed(self, state: GraphExecutionState, node: NodeDefinition) -> None:
        incomplete = [
            dependency
            for dependency in node.depends_on
            if state.node_records[dependency].status != NodeStatus.COMPLETED
        ]
        if incomplete:
            raise RuntimeError(f"节点 {node.node_id} 依赖未完成: {incomplete}")

    def _handle_interrupts(self, state: GraphExecutionState, controller: InterruptController) -> None:
        for command in controller.drain():
            self._apply_interrupt_command(state, controller, command)

    def _wait_until_resumed(self, state: GraphExecutionState, controller: InterruptController) -> None:
        while controller.is_paused():
            controller.wait_if_paused(timeout=0.1)
            self._handle_interrupts(state, controller)

    def _apply_interrupt_command(
        self,
        state: GraphExecutionState,
        _controller: InterruptController,
        command: InterruptCommand,
    ) -> None:
        payload = command.payload
        if command.action == InterruptAction.PAUSE:
            state.status = GraphStatus.PAUSED
            if state.current_node_id:
                state.node_records[state.current_node_id].status = NodeStatus.PAUSED
            self._emit(state, "graph_paused", state.current_node_id, payload=payload)
            self._snapshot(state, "graph_paused")
            self._persist_state(state, "graph_paused")
            return

        if command.action == InterruptAction.RESUME:
            state.status = GraphStatus.RUNNING
            if state.current_node_id and state.node_records[state.current_node_id].status == NodeStatus.PAUSED:
                state.node_records[state.current_node_id].status = NodeStatus.RUNNING
            self._emit(state, "graph_resumed", state.current_node_id, payload=payload)
            self._snapshot(state, "graph_resumed")
            self._persist_state(state, "graph_resumed")
            return

        if command.action == InterruptAction.UPDATE_INPUTS:
            updates = dict(payload.get("graph_context_updates", {}))
            request_updates = dict(payload.get("request_updates", {}))
            state.graph_context.update(updates)
            if request_updates:
                state.graph_context.setdefault("request", {}).update(request_updates)
            self._emit(state, "graph_inputs_updated", state.current_node_id, payload=payload)
            self._snapshot(state, "graph_inputs_updated")
            self._persist_state(state, "graph_inputs_updated")
            return

        if command.action == InterruptAction.JUMP_TO_NODE:
            target_node_id = payload["target_node_id"]
            self._jump_to_node(state, target_node_id)
            self._emit(state, "graph_jumped", target_node_id, payload=payload)
            self._snapshot(state, "graph_jumped")
            self._persist_state(state, "graph_jumped")
            return

        if command.action == InterruptAction.ROLLBACK_TO_SNAPSHOT:
            snapshot_payload = self.store.load_snapshot(
                state.metadata.user_id,
                state.metadata.session_id,
                payload["snapshot_id"],
            )
            snapshot = snapshot_from_dict(snapshot_payload)
            state.current_node_id = snapshot.current_node_id
            state.graph_context = dict(snapshot.graph_context)
            state.node_records = dict(snapshot.node_records)
            state.completed_order = list(snapshot.completed_order)
            state.restored_from_snapshot = snapshot.snapshot_id
            state.status = GraphStatus.RESTORED
            self._emit(state, "graph_rolled_back", state.current_node_id, payload=payload)
            self._snapshot(state, "graph_rolled_back")
            self._persist_state(state, "graph_rolled_back")

    def _jump_to_node(self, state: GraphExecutionState, target_node_id: str) -> None:
        if target_node_id not in state.node_records:
            raise KeyError(f"目标节点不存在: {target_node_id}")
        topology = list(state.graph_context["topology"])
        target_index = topology.index(target_node_id)
        state.current_node_id = target_node_id
        state.completed_order = [node_id for node_id in state.completed_order if topology.index(node_id) < target_index]
        for node_id in topology[target_index:]:
            record = state.node_records[node_id]
            if node_id == target_node_id:
                record.status = NodeStatus.READY
            else:
                record.status = NodeStatus.PENDING
            record.output = None
            record.error = None
            record.stream_chunks = []
            if node_id in state.graph_context:
                del state.graph_context[node_id]
        for node in state.definition.nodes:
            if node.output_key and node.output_key in state.graph_context and topology.index(node.node_id) >= target_index:
                del state.graph_context[node.output_key]

    def _emit(
        self,
        state: GraphExecutionState,
        event_type: str,
        node_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        state.event_sequence += 1
        event = GraphEvent(
            sequence=state.event_sequence,
            event_type=event_type,
            user_id=state.metadata.user_id,
            session_id=state.metadata.session_id,
            graph_id=state.metadata.graph_id,
            node_id=node_id,
            payload=payload or {},
        )
        self.store.append_event(state, event)

    def _snapshot(self, state: GraphExecutionState, reason: str) -> None:
        state.snapshot_sequence += 1
        snapshot = GraphSnapshot(
            snapshot_id=str(uuid.uuid4()),
            sequence=state.snapshot_sequence,
            reason=reason,
            created_at=utc_now(),
            graph_status=state.status,
            current_node_id=state.current_node_id,
            graph_context=dict(state.graph_context),
            node_records={node_id: NodeExecutionRecord(**asdict(record)) for node_id, record in state.node_records.items()},
            completed_order=list(state.completed_order),
        )
        self.store.save_snapshot(state, snapshot)

    def _persist_state(self, state: GraphExecutionState, _reason: str) -> None:
        state.metadata.updated_at = utc_now()
        self.store.save_state(state)
