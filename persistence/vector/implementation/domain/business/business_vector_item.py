from dataclasses import dataclass, field
from typing import Any


@dataclass
class BusinessVectorItem:
    """业务层向量条目 - 业务层：仅保留业务逻辑所需的核心属性"""
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    chunk_type: str = "text"