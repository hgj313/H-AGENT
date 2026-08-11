from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None


@dataclass
class VectorItem:
    """向量条目 - 底层实现层保留完整的 ChromaDB API 属性"""
    id: str
    content: str
    vector: Optional[list[float]] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    chunk_type: str = "text"
    uri: Optional[str] = None
    data: Optional[Any] = None

    @staticmethod
    def _to_list(value: Any, index: int) -> Any:
        """安全提取列表元素，并处理 numpy 数组"""
        if value is None:
            return None
        if isinstance(value, list):
            return value[index] if index < len(value) else None
        if HAS_NUMPY and isinstance(value, np.ndarray):
            return value[index].tolist() if index < len(value) else None
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "vector": self.vector,
            "metadata": self.metadata,
            "chunk_index": self.chunk_index,
            "chunk_type": self.chunk_type,
            "uri": self.uri,
            "data": self.data
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VectorItem":
        return cls(
            id=data["id"],
            content=data["content"],
            vector=data.get("vector"),
            metadata=data.get("metadata", {}),
            chunk_index=data.get("chunk_index", 0),
            chunk_type=data.get("chunk_type", "text"),
            uri=data.get("uri"),
            data=data.get("data")
        )
    
    @classmethod
    def from_chroma_result(cls, item_id: str, index: int, chroma_result: dict) -> "VectorItem":
        """从 ChromaDB GetResult 创建 VectorItem，保留完整 API 属性"""
        embeddings = chroma_result.get('embeddings')
        documents = chroma_result.get('documents')
        metadatas = chroma_result.get('metadatas')
        uris = chroma_result.get('uris')
        data = chroma_result.get('data')
        
        return cls(
            id=item_id,
            vector=cls._to_list(embeddings, index),
            content=cls._to_list(documents, index) or "",
            metadata=cls._to_list(metadatas, index) or {},
            uri=cls._to_list(uris, index),
            data=cls._to_list(data, index)
        )