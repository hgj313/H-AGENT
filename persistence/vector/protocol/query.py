from abc import ABC, abstractmethod
from typing import Optional

from persistence.vector.implementation.domain.QueryResult import QueryResult
from persistence.vector.protocol.embedding import BaseEmbedder
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.protocol.engine import BaseSearchEngine


class BaseVectorSearcher(ABC):
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
    def search(
        self,
        query_text: str,
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[QueryResult]:
        pass

    def _embed_query(self, text: str) -> list[float]:
        vectors = self._embedder.embed_documents([text])
        return vectors[0]

    def _convert_to_results(
        self,
        items: list,
        scores: list[float]
    ) -> list[QueryResult]:
        return [
            QueryResult(
                content=item.content,
                score=scores[i],
                metadata=item.metadata,
                rank=i,
                id=item.id
            )
            for i, item in enumerate(items)
        ]