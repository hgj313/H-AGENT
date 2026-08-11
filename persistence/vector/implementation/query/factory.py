"""
查询器工厂 - 创建 BaseVectorSearcher 实例（query 层职责）

注意：SearchEngineFactory（底层引擎工厂）属于 engine 层，定义在：
    persistence.vector.implementation.engine.factory
"""
from typing import Optional

from persistence.vector.protocol.embedding import BaseEmbedder
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.protocol.engine import BaseSearchEngine
from persistence.vector.protocol.query import BaseVectorSearcher
from persistence.vector.implementation.query.list_based_searcher import ListBasedVectorSearcher


class VectorSearcherFactory:
    """向量查询器工厂（query 层）"""

    _REGISTRY: dict[str, type[BaseVectorSearcher]] = {
        "list_based": ListBasedVectorSearcher,
        # 兼容旧类型名
        "similarity": ListBasedVectorSearcher,
        "chroma": ListBasedVectorSearcher,
    }

    @classmethod
    def create(
        cls,
        searcher_type: str = "list_based",
        embedder: Optional[BaseEmbedder] = None,
        storage: Optional[BaseVectorStorage] = None,
        search_engine: Optional[BaseSearchEngine] = None,
        **kwargs
    ) -> BaseVectorSearcher:
        if embedder is None or storage is None:
            raise ValueError("embedder and storage are required for VectorSearcherFactory.create")

        searcher_cls = cls._REGISTRY.get(searcher_type.lower())
        if searcher_cls is None:
            raise ValueError(
                f"Unknown searcher type: {searcher_type}. "
                f"Available: {list(cls._REGISTRY.keys())}"
            )
        return searcher_cls(
            embedder=embedder,
            storage=storage,
            search_engine=search_engine,
            **kwargs
        )

    @classmethod
    def register(cls, name: str, searcher_cls: type) -> None:
        cls._REGISTRY[name.lower()] = searcher_cls

    @classmethod
    def list_available(cls) -> list[str]:
        return list(cls._REGISTRY.keys())
