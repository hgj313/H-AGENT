from dataclasses import dataclass, field
from typing import Any, Optional

from ._utils import _to_list_safe


@dataclass
class ChromaSearchItem:
    """ChromaDB 单条搜索结果项 - 耦合层：完整映射 ChromaDB QueryResult API"""
    id: str
    distance: float
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: Optional[list[float]] = None
    uri: Optional[str] = None
    
    @classmethod
    def from_chroma_result(cls, index: int, chroma_result: dict) -> "ChromaSearchItem":
        """从 ChromaDB QueryResult 批量结果中提取单条"""
        ids = chroma_result.get('ids', [[]])
        distances = chroma_result.get('distances', [[]])
        documents = chroma_result.get('documents', [[]])
        metadatas = chroma_result.get('metadatas', [[]])
        embeddings = chroma_result.get('embeddings', [[]])
        uris = chroma_result.get('uris', [[]])
        
        ids_list = ids[0] if ids and len(ids) > 0 else []
        distances_list = distances[0] if distances and len(distances) > 0 else []
        documents_list = documents[0] if documents and len(documents) > 0 else []
        metadatas_list = metadatas[0] if metadatas and len(metadatas) > 0 else []
        embeddings_list = embeddings[0] if embeddings and len(embeddings) > 0 else None
        uris_list = uris[0] if uris and len(uris) > 0 else []
        
        return cls(
            id=_to_list_safe(ids_list, index, ""),
            distance=_to_list_safe(distances_list, index, 1.0),
            document=_to_list_safe(documents_list, index, ""),
            metadata=_to_list_safe(metadatas_list, index, {}),
            embedding=_to_list_safe(embeddings_list, index),
            uri=_to_list_safe(uris_list, index)
        )