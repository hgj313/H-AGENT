from abc import ABC, abstractmethod
from typing import Optional

from persistence.vector.implementation.domain.business import BusinessQueryResult
from persistence.vector.protocol.embedding import BaseEmbedder
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.protocol.engine import BaseSearchEngine


class BaseVectorSearcher(ABC):
    """向量查询器统一接口（列表式）

    设计原则：
        - 唯一入口 batch_search(query_texts, ...) -> list[list[BusinessQueryResult]]
        - 单条查询 = list 长度为 1
    """
    def __init__(
        self,
        embedder: BaseEmbedder,
        storage: BaseVectorStorage,
        search_engine: Optional[BaseSearchEngine] = None
    ):
        self._embedder = embedder
        self._storage = storage
        self._search_engine = search_engine

    def set_search_engine(self, search_engine: BaseSearchEngine) -> None:
        self._search_engine = search_engine

    @abstractmethod
    def batch_search(
        self,
        query_texts: list[str],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[list[BusinessQueryResult]]:
        """批量自然语言查询（统一入口）"""
        pass

    def _embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed_documents(texts)

    def _convert_to_results(
        self,
        items: list,
        scores: list[float]
    ) -> list[BusinessQueryResult]:
        return [
            BusinessQueryResult(
                id=item.id,
                content=item.content,
                score=scores[i],
                metadata=item.metadata,
                rank=i
            )
            for i, item in enumerate(items)
        ]
