from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock, Thread
from typing import Any

from agent.graphs.simple_graph.runtime.interrupts import InterruptController


@dataclass(slots=True)
class SessionRuntime:
    user_id: str
    session_id: str
    controller: InterruptController = field(default_factory=InterruptController)
    thread: Thread | None = None
    status: str = "idle"
    latest_payload: dict[str, Any] = field(default_factory=dict)


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], SessionRuntime] = {}
        self._lock = Lock()

    def get_or_create(self, user_id: str, session_id: str) -> SessionRuntime:
        key = (user_id, session_id)
        with self._lock:
            runtime = self._sessions.get(key)
            if runtime is None:
                runtime = SessionRuntime(user_id=user_id, session_id=session_id)
                self._sessions[key] = runtime
            return runtime

    def get(self, user_id: str, session_id: str) -> SessionRuntime:
        key = (user_id, session_id)
        with self._lock:
            if key not in self._sessions:
                raise KeyError(f"会话不存在: {session_id}")
            return self._sessions[key]
