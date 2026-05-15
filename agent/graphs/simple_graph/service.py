from __future__ import annotations

import time
import uuid
from threading import Thread
from typing import Any

from agent.graphs.simple_graph.demo.graph_factory import build_demo_graph
from agent.graphs.simple_graph.executor import GraphExecutor
from agent.graphs.simple_graph.models import InterruptAction
from agent.graphs.simple_graph.runtime.interrupts import InterruptCommand
from agent.graphs.simple_graph.runtime.session_manager import SessionRegistry
from agent.graphs.simple_graph.storage.file_store import FileSystemGraphStore


class GraphService:
    def __init__(self, root_dir: str | None = None) -> None:
        self.store = FileSystemGraphStore(root_dir=root_dir)
        self.registry = SessionRegistry()
        self.executor = GraphExecutor(store=self.store)

    def create_session(self, user_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        definition = build_demo_graph()
        state = self.executor.create_state(user_id, session_id, definition, request_payload)
        runtime = self.registry.get_or_create(user_id, session_id)
        runtime.latest_payload = request_payload
        return {
            "user_id": user_id,
            "session_id": session_id,
            "graph_id": definition.graph_id,
            "status": state.status,
        }

    def start_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        runtime = self.registry.get_or_create(user_id, session_id)
        state = self.executor.load_state(user_id, session_id, requester_user_id=user_id)

        if runtime.thread and runtime.thread.is_alive():
            return {"status": "already_running", "session_id": session_id}

        def _run() -> None:
            runtime.status = "running"
            self.executor.execute(state, runtime.controller)
            runtime.status = "finished"

        runtime.thread = Thread(target=_run, name=f"graph-session-{session_id}", daemon=True)
        runtime.thread.start()
        return {"status": "started", "session_id": session_id}

    def interrupt(self, user_id: str, session_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime = self.registry.get(user_id, session_id)
        command = InterruptCommand(action=InterruptAction(action), payload=payload or {})
        runtime.controller.submit(command)
        return {"accepted": True, "action": action, "session_id": session_id}

    def get_state(self, user_id: str, session_id: str) -> dict[str, Any]:
        return self.executor.load_state(user_id, session_id, requester_user_id=user_id).to_dict()

    def list_snapshots(self, user_id: str, session_id: str) -> list[str]:
        return self.executor.list_snapshots(user_id, session_id, requester_user_id=user_id)

    def rollback(self, user_id: str, session_id: str, snapshot_id: str) -> dict[str, Any]:
        state = self.executor.restore_from_snapshot(
            user_id,
            session_id,
            snapshot_id,
            requester_user_id=user_id,
        )
        return state.to_dict()

    def replay_events(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        return self.executor.replay(user_id, session_id, requester_user_id=user_id)

    def stream_events(self, user_id: str, session_id: str, after_sequence: int = 0):
        last_sequence = after_sequence
        while True:
            events = self.store.load_events(user_id, session_id)
            fresh_events = [event for event in events if event["sequence"] > last_sequence]
            for event in fresh_events:
                last_sequence = event["sequence"]
                yield event

            try:
                state = self.get_state(user_id, session_id)
            except FileNotFoundError:
                break

            if state["status"] in {"completed", "failed"} and not fresh_events:
                break
            time.sleep(0.2)
