from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class QueryResult:
    """查询结果 - 上层业务逻辑使用的精简属性"""
    id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    rank: int = 0
    distance: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
            "rank": self.rank,
            "distance": self.distance
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QueryResult":
        return cls(
            id=data.get("id", ""),
            content=data["content"],
            score=data["score"],
            metadata=data.get("metadata", {}),
            rank=data.get("rank", 0),
            distance=data.get("distance")
        )
    
    @classmethod
    def from_search_result(cls, item_id: str, content: str, score: float, 
                          distance: Optional[float], metadata: dict, rank: int) -> "QueryResult":
        """从搜索结果创建 QueryResult，上层使用精简属性"""
        return cls(
            id=item_id,
            content=content,
            score=score,
            metadata=metadata,
            rank=rank,
            distance=distance
        )