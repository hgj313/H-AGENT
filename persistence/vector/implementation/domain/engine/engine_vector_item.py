from dataclasses import dataclass, field
from typing import Any, Optional

from persistence.vector.implementation.domain.adapter import _to_list_safe


@dataclass
class EngineVectorItem:
    """引擎层向量条目 - 传输层：封装搜索引擎运行所需的属性"""
    id: str
    content: str = ""
    vector: Optional[list[float]] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    chunk_type: str = "text"
    uri: Optional[str] = None
    data: Optional[Any] = None

    @classmethod
    def from_chroma_result(cls, item_id: str, index: int, chroma_result: dict) -> "EngineVectorItem":
        """从 ChromaDB GetResult 创建 EngineVectorItem"""
        embeddings = chroma_result.get('embeddings')
        documents = chroma_result.get('documents')
        metadatas = chroma_result.get('metadatas')
        uris = chroma_result.get('uris')
        data = chroma_result.get('data')
        
        return cls(
            id=item_id,
            content=_to_list_safe(documents, index) or "",
            vector=_to_list_safe(embeddings, index),
            metadata=_to_list_safe(metadatas, index) or {},
            uri=_to_list_safe(uris, index),
            data=_to_list_safe(data, index)
        )