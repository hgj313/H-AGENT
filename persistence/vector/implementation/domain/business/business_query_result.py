from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BusinessQueryResult:
    """业务层查询结果 - 业务层：仅保留业务逻辑所需的核心属性"""
    id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    rank: int = 0
    distance: Optional[float] = None