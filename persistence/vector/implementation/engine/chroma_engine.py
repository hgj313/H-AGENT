"""
ChromaDB 搜索引擎实现
"""
import logging
from typing import Optional, Literal

from persistence.vector.protocol.engine import BaseSearchEngine
from persistence.vector.implementation.store import ChromaVectorStorage
from persistence.vector.implementation.domain.engine import EngineSearchResult

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
                include=["metadatas", "documents", "distances", "embeddings"]
            )
            
            if not results['ids'] or not results['ids'][0]:
                return []
            print(results)
            print("="*50)
            
            raw_results = []
            metric = self.distance_metric
            for i, vector_id in enumerate(results['ids'][0]):
                distance = results['distances'][0][i] if 'distances' in results else 1.0
                similarity_score = self.calculate_similarity(distance, metric)
                raw_results.append((vector_id, [similarity_score, distance]))
            
            return raw_results
            
        except Exception as e:
            logger.error(f"ChromaDB query failed: {e}")
            return []
    
    def search_full(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[EngineSearchResult]:
        """返回完整的 ChromaDB 查询结果，包含所有 API 属性"""
        if k <= 0:
            return []
        
        where_filter = filter_metadata if filter_metadata else None
        
        try:
            results = self._collection.query(
                query_embeddings=[query_vector],
                n_results=k,
                where=where_filter,
                include=["metadatas", "documents", "distances", "embeddings"]
            )
            
            if not results['ids'] or not results['ids'][0]:
                return []
            
            search_results = []
            metric = self.distance_metric
            ids_list = results['ids'][0]
            distances_list = results.get('distances', [[]])[0]
            documents_list = results.get('documents', [[]])[0]
            metadatas_list = results.get('metadatas', [[]])[0]
            embeddings_list = results.get('embeddings', [[]])[0]
            
            for i, vector_id in enumerate(ids_list):
                distance = distances_list[i] if i < len(distances_list) else 1.0
                similarity_score = self.calculate_similarity(distance, metric)
                document = documents_list[i] if i < len(documents_list) else ""
                metadata = metadatas_list[i] if i < len(metadatas_list) else {}
                embedding = embeddings_list[i] if i < len(embeddings_list) else None
                
                search_results.append(EngineSearchResult(
                    id=vector_id,
                    distance=distance,
                    similarity=similarity_score,
                    content=document,
                    metadata=metadata,
                    embedding=embedding
                ))
            
            return search_results
            
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
            metric = self.distance_metric
            for i, vector_id in enumerate(results['ids'][0]):
                distance = results['distances'][0][i] if 'distances' in results else 1.0
                similarity_score = self.calculate_similarity(distance, metric)
                raw_results.append((vector_id, similarity_score, distance))
            
            return raw_results
            
        except Exception as e:
            logger.error(f"ChromaDB query failed: {e}")
            return []