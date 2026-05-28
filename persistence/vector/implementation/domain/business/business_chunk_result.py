from dataclasses import dataclass, field
from typing import Any


@dataclass
class BusinessChunkResult:
    """业务层切分结果 - 业务层：仅保留业务逻辑所需的核心属性"""
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    chunk_type: str = "text"
    header_path: list[str] = field(default_factory=list)