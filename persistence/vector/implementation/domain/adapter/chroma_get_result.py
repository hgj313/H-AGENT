from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None


@dataclass 
class ChromaGetResult:
    """ChromaDB Get 结果 - 耦合层：完整映射 ChromaDB GetResult API"""
    ids: list[str]
    embeddings: Optional[list[list[float]]] = None
    documents: Optional[list[str]] = None
    metadatas: Optional[list[dict[str, Any]]] = None
    uris: Optional[list[str]] = None
    data: Optional[list[Any]] = None
    included: Optional[list[str]] = None
    
    @classmethod
    def from_chroma_response(cls, response: dict) -> "ChromaGetResult":
        """从 ChromaDB API 响应创建 - 保留原始数据类型"""
        embeddings = response.get('embeddings')
        if HAS_NUMPY and embeddings is not None and isinstance(embeddings, np.ndarray):
            embeddings = embeddings.tolist()
        
        return cls(
            ids=response.get('ids', []),
            embeddings=embeddings,
            documents=response.get('documents'),
            metadatas=response.get('metadatas'),
            uris=response.get('uris'),
            data=response.get('data'),
            included=response.get('included')
        )