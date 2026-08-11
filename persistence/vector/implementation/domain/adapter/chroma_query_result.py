from dataclasses import dataclass, field
from typing import Any, Optional

from ._utils import _to_list_safe


@dataclass
class ChromaQueryResult:
    """ChromaDB 查询结果 - 耦合层：完整映射 ChromaDB QueryResult API"""
    ids: list[str]
    distances: list[float]
    documents: list[str]
    metadatas: list[dict[str, Any]]
    embeddings: Optional[list[list[float]]] = None
    uris: Optional[list[str]] = None
    included: Optional[list[str]] = None
    
    @classmethod
    def from_chroma_response(cls, response: dict) -> "ChromaQueryResult":
        """从 ChromaDB API 响应创建"""
        ids_raw = response.get('ids', [[]])
        distances_raw = response.get('distances', [[]])
        documents_raw = response.get('documents', [[]])
        metadatas_raw = response.get('metadatas', [[]])
        
        return cls(
            ids=ids_raw[0] if ids_raw and len(ids_raw) > 0 else [],
            distances=distances_raw[0] if distances_raw and len(distances_raw) > 0 else [],
            documents=documents_raw[0] if documents_raw and len(documents_raw) > 0 else [],
            metadatas=metadatas_raw[0] if metadatas_raw and len(metadatas_raw) > 0 else [],
            embeddings=response.get('embeddings'),
            uris=response.get('uris', [[]])[0] if response.get('uris') else None,
            included=response.get('included')
        )