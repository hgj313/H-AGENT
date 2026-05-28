from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryResult:
    """查询结果"""
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    rank: int = 0
    id: str = ""

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
            "rank": self.rank,
            "id": self.id
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QueryResult":
        return cls(
            content=data["content"],
            score=data["score"],
            metadata=data.get("metadata", {}),
            rank=data.get("rank", 0),
            id=data.get("id", "")
        )