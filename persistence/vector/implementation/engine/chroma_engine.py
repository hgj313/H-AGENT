"""
ChromaDB 搜索引擎实现（列表式统一接口）
"""
import logging
from typing import Optional, Literal

from persistence.vector.protocol.engine import BaseSearchEngine
from persistence.vector.implementation.store import ChromaVectorStorage
from persistence.vector.implementation.domain.engine import EngineSearchResult

logger = logging.getLogger(__name__)


class ChromaSearchEngine(BaseSearchEngine):
    """ChromaDB 查询引擎实现（统一 batch_search 入口）"""

    def __init__(
        self,
        storage: ChromaVectorStorage,
        default_k: int = 4
    ):
        self._storage = storage
        self._default_k = default_k
        self._collection = storage._collection

    @property
    def distance_metric(self) -> Literal["cosine", "l2", "ip"]:
        return self._storage.distance_metric

    def refresh(self) -> None:
        self._collection = self._storage._collection

    @staticmethod
    def calculate_similarity(distance: float, metric: str) -> float:
        if metric == "cosine":
            return 1.0 - distance
        elif metric == "l2":
            return 1.0 / (1.0 + distance)
        elif metric == "ip":
            return max(0, (1.0 + distance) / 2)
        return 1.0 - distance

    def batch_search(
        self,
        query_vectors: list[list[float]],
        k: int = 4,
        filter_metadata: Optional[dict] = None,
        include_full: bool = False
    ) -> list[list[tuple[str, list[float]]]]:
        """统一批量查询入口（原生 Chroma batch，单次 RTT）

        Args:
            query_vectors: 多条 query 向量；单条场景传 [vector]
            k: 每条 query 的 top-k
            filter_metadata: where filter（所有 query 共享）
            include_full:
                False -> 返回 [(id, [sim, dist])]
                True  -> 返回 [(id, [sim, dist, content, metadata, embedding])]

        Returns:
            list[list[(vector_id, score_vector)]]，外层 index 对应 query
        """
        if not query_vectors or k <= 0:
            return [[] for _ in range(len(query_vectors))]

        where_filter = filter_metadata if filter_metadata else None
        include_fields = (
            ["metadatas", "documents", "distances", "embeddings"]
            if include_full else
            ["metadatas", "documents", "distances"]
        )

        try:
            results = self._collection.query(
                query_embeddings=query_vectors,
                n_results=k,
                where=where_filter,
                include=include_fields
            )

            ids_batch = results.get('ids', []) or []
            distances_batch = results.get('distances', []) or []
            documents_batch = results.get('documents', []) or []
            metadatas_batch = results.get('metadatas', []) or []
            embeddings_batch = results.get('embeddings', []) or []
            metric = self.distance_metric

            batched: list[list[tuple[str, list[float]]]] = []
            for q_idx, ids in enumerate(ids_batch):
                distances = distances_batch[q_idx] if q_idx < len(distances_batch) else []
                documents = documents_batch[q_idx] if q_idx < len(documents_batch) else []
                metadatas = metadatas_batch[q_idx] if q_idx < len(metadatas_batch) else []
                embeddings = embeddings_batch[q_idx] if q_idx < len(embeddings_batch) else []

                per_query: list[tuple[str, list[float]]] = []
                for i, vector_id in enumerate(ids):
                    distance = distances[i] if i < len(distances) else 1.0
                    similarity_score = self.calculate_similarity(distance, metric)

                    if include_full:
                        score_vector: list[float | str | dict] = [
                            similarity_score,
                            distance,
                            documents[i] if i < len(documents) else "",
                            metadatas[i] if i < len(metadatas) else {},
                            embeddings[i] if i < len(embeddings) else None,
                        ]
                    else:
                        score_vector = [similarity_score, distance]

                    per_query.append((vector_id, score_vector))
                batched.append(per_query)

            return batched

        except Exception as e:
            logger.error(f"ChromaDB batch query failed: {e}")
            return [[] for _ in range(len(query_vectors))]
