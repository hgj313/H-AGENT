from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def now_ts() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class GraphEvent:
    sequence: int
    event_type: str
    user_id: str
    session_id: str
    graph_id: str
    node_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
