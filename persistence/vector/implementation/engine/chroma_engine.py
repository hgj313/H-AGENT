"""
ChromaDB 搜索引擎实现
"""
import logging
from typing import Optional

from persistence.vector.protocol.engine import BaseSearchEngine
from persistence.vector.implementation.store import ChromaVectorStorage

logger = logging.getLogger(__name__)


class ChromaSearchEngine(BaseSearchEngine):
    """ChromaDB 查询引擎实现"""
    
    def __init__(
        self,
        storage: ChromaVectorStorage,
        default_k: int = 4
    ):
        self._storage = storage
        self._default_k = default_k
        self._collection = storage._collection
    
    def refresh(self) -> None:
        self._collection = self._storage._collection
    
    def search(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[tuple[str, list[float]]]:
        if k <= 0:
            return []
        
        where_filter = filter_metadata if filter_metadata else None
        
        try:
            results = self._collection.query(
                query_embeddings=[query_vector],
                n_results=k,
                where=where_filter,
                include=["metadatas", "distances"]
            )
            
            if not results['ids'] or not results['ids'][0]:
                return []
            
            raw_results = []
            for i, vector_id in enumerate(results['ids'][0]):
                distance = results['distances'][0][i] if 'distances' in results else 1.0
                similarity_score = 1.0 - distance if distance <= 1.0 else 0.0
                raw_results.append((vector_id, [similarity_score, distance]))
            
            return raw_results
            
        except Exception as e:
            logger.error(f"ChromaDB query failed: {e}")
            return []
    
    def search_with_scores(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[tuple[str, float, float]]:
        if k <= 0:
            return []
        
        where_filter = filter_metadata if filter_metadata else None
        
        try:
            results = self._collection.query(
                query_embeddings=[query_vector],
                n_results=k,
                where=where_filter,
                include=["metadatas", "distances"]
            )
            
            if not results['ids'] or not results['ids'][0]:
                return []
            
            raw_results = []
            for i, vector_id in enumerate(results['ids'][0]):
                distance = results['distances'][0][i] if 'distances' in results else 1.0
                similarity_score = 1.0 - distance if distance <= 1.0 else 0.0
                raw_results.append((vector_id, similarity_score, distance))
            
            return raw_results
            
        except Exception as e:
            logger.error(f"ChromaDB query failed: {e}")
            return []