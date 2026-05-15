from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any

from agent.graphs.simple_graph.models import InterruptAction


@dataclass(slots=True)
class InterruptCommand:
    action: InterruptAction
    payload: dict[str, Any] = field(default_factory=dict)


class InterruptController:
    def __init__(self) -> None:
        self._pending_commands: list[InterruptCommand] = []
        self._lock = Lock()
        self._pause_event = Event()
        self._pause_event.set()

    def submit(self, command: InterruptCommand) -> None:
        with self._lock:
            self._pending_commands.append(command)
        if command.action == InterruptAction.PAUSE:
            self._pause_event.clear()
        if command.action == InterruptAction.RESUME:
            self._pause_event.set()

    def drain(self) -> list[InterruptCommand]:
        with self._lock:
            commands = list(self._pending_commands)
            self._pending_commands.clear()
            return commands

    def wait_if_paused(self, timeout: float = 0.1) -> bool:
        return self._pause_event.wait(timeout=timeout)

    def is_paused(self) -> bool:
        return not self._pause_event.is_set()
