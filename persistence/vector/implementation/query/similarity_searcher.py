import logging
from typing import Optional

from persistence.vector.protocol.query import BaseVectorSearcher
from persistence.vector.protocol.engine import BaseSearchEngine
from persistence.vector.implementation.domain import QueryResult

logger = logging.getLogger(__name__)


class SimilaritySearcher(BaseVectorSearcher):
    def __init__(
        self,
        embedder,
        storage,
        default_k: int = 4,
        min_score: float = 0.0,
        search_engine: Optional[BaseSearchEngine] = None
    ):
        self._embedder = embedder
        self._storage = storage
        self._search_engine = search_engine
        self.default_k = default_k
        self.min_score = min_score

    def set_search_engine(self, search_engine: BaseSearchEngine) -> None:
        self._search_engine = search_engine

    def search(
        self,
        query_text: str,
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[QueryResult]:
        vectors = self._embedder.embed_documents([query_text])
        query_vector = vectors[0]
        
        if self._search_engine is not None:
            self._search_engine.refresh()
            raw_results = self._search_engine.search(
                query_vector,
                k=k,
                filter_metadata=filter_metadata
            )
            results = self._convert_from_engine_results(raw_results)
        else:
            raise NotImplementedError("Query engine is required for search")
        
        if self.min_score > 0:
            results = [r for r in results if r.score >= self.min_score]
        return results

    def _convert_from_engine_results(
        self,
        raw_results: list[tuple[str, list[float]]]
    ) -> list[QueryResult]:
        if not raw_results:
            return []
        
        ids = [id_ for id_, _ in raw_results]
        vectors = self._storage.get_vectors(ids)
        id_to_vector = {v.id: v for v in vectors}
        
        return [
            QueryResult(
                content=id_to_vector[id_].content if id_ in id_to_vector else "",
                score=score_vector[0],
                metadata=id_to_vector[id_].metadata if id_ in id_to_vector else {},
                rank=i,
                id=id_
            )
            for i, (id_, score_vector) in enumerate(raw_results)
        ]