from dataclasses import dataclass, field
from typing import Any


@dataclass
class VectorItem:
    """向量条目"""
    id: str
    content: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    chunk_type: str = "text"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "vector": self.vector,
            "metadata": self.metadata,
            "chunk_index": self.chunk_index,
            "chunk_type": self.chunk_type
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VectorItem":
        return cls(
            id=data["id"],
            content=data["content"],
            vector=data["vector"],
            metadata=data.get("metadata", {}),
            chunk_index=data.get("chunk_index", 0),
            chunk_type=data.get("chunk_type", "text")
        )