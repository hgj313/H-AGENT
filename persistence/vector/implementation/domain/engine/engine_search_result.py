from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class EngineSearchResult:
    """引擎层搜索结果 - 传输层：封装搜索引擎返回的核心属性"""
    id: str
    distance: float
    similarity: float
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: Optional[list[float]] = None