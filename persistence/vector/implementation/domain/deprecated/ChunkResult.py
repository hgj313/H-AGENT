from dataclasses import dataclass, field
from typing import Any

@dataclass
class ChunkResult:
    """切分结果"""
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    chunk_type: str = "text"
    header_path: list[str] = field(default_factory=list)