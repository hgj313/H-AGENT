from __future__ import annotations

import json
import os
import uuid
from threading import RLock
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent.graphs.simple_graph.events import GraphEvent
from agent.graphs.simple_graph.models import GraphExecutionState, GraphSnapshot


class FileSystemGraphStore:
    def __init__(self, root_dir: str | Path | None = None) -> None:
        self.root_dir = Path(root_dir or Path.cwd() / ".graph_runtime").resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._file_lock = RLock()

    def ensure_session_scope(self, user_id: str, session_id: str) -> Path:
        session_dir = self.root_dir / "users" / user_id / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        return session_dir

    def validate_scope(self, requester_user_id: str, target_user_id: str) -> None:
        if requester_user_id != target_user_id:
            raise PermissionError("禁止跨用户访问图运行数据")

    def session_dir(self, user_id: str, session_id: str) -> Path:
        return self.root_dir / "users" / user_id / "sessions" / session_id

    def save_state(self, state: GraphExecutionState) -> Path:
        session_dir = self.ensure_session_scope(state.metadata.user_id, state.metadata.session_id)
        state_path = session_dir / "state.json"
        self._atomic_write_json(state_path, state.to_dict())
        return state_path

    def load_state(self, user_id: str, session_id: str) -> dict[str, Any]:
        state_path = self.session_dir(user_id, session_id) / "state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"未找到会话状态: {session_id}")
        with self._file_lock:
            content = state_path.read_text(encoding="utf-8").strip()
        if not content:
            raise RuntimeError(f"会话状态文件为空: {session_id}")
        return json.loads(content)

    def append_event(self, state: GraphExecutionState, event: GraphEvent) -> None:
        session_dir = self.ensure_session_scope(state.metadata.user_id, state.metadata.session_id)
        event_path = session_dir / "events.jsonl"
        with self._file_lock:
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def load_events(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        event_path = self.session_dir(user_id, session_id) / "events.jsonl"
        if not event_path.exists():
            return []
        with self._file_lock:
            return [
                json.loads(line)
                for line in event_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    def save_snapshot(self, state: GraphExecutionState, snapshot: GraphSnapshot) -> Path:
        session_dir = self.ensure_session_scope(state.metadata.user_id, state.metadata.session_id)
        snapshot_path = session_dir / "snapshots" / f"{snapshot.sequence:04d}_{snapshot.snapshot_id}.json"
        snapshot_payload = asdict(snapshot)
        self._atomic_write_json(snapshot_path, snapshot_payload)
        return snapshot_path

    def list_snapshots(self, user_id: str, session_id: str) -> list[Path]:
        snapshot_dir = self.session_dir(user_id, session_id) / "snapshots"
        if not snapshot_dir.exists():
            return []
        with self._file_lock:
            return sorted(snapshot_dir.glob("*.json"))

    def load_snapshot(self, user_id: str, session_id: str, snapshot_id: str) -> dict[str, Any]:
        for path in self.list_snapshots(user_id, session_id):
            if path.stem.endswith(snapshot_id):
                with self._file_lock:
                    return json.loads(path.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"未找到快照: {snapshot_id}")

    def _atomic_write_json(self, target_path: Path, payload: dict[str, Any]) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f"{target_path.name}.{uuid.uuid4().hex}.tmp")
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        with self._file_lock:
            temp_path.write_text(content, encoding="utf-8")
            os.replace(temp_path, target_path)
