from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class EngineVectorItem:
    """引擎层向量条目 - 传输层：封装搜索引擎运行所需的属性"""
    id: str
    vector: Optional[list[float]] = None
    document: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    chunk_type: str = "text"
    uri: Optional[str] = None
    data: Optional[Any] = None

    @staticmethod
    def _to_list_safe(value: Any, index: int, default: Any = None) -> Any:
        """安全提取列表元素，处理 numpy 数组和 None 情况"""
        if value is None:
            return default
        if isinstance(value, list):
            return value[index] if index < len(value) else default
        try:
            import numpy as np
            if isinstance(value, np.ndarray):
                return value[index].tolist() if index < len(value) else default
        except ImportError:
            pass
        return default

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
            vector=cls._to_list_safe(embeddings, index),
            document=cls._to_list_safe(documents, index) or "",
            content=cls._to_list_safe(documents, index) or "",
            metadata=cls._to_list_safe(metadatas, index) or {},
            uri=cls._to_list_safe(uris, index),
            data=cls._to_list_safe(data, index)
        )