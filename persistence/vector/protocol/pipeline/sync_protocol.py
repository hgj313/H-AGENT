from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Any

from persistence.vector.protocol.pipeline.base_protocol import BaseVectorPipeline
from persistence.vector.protocol.pipeline.config import PipelineConfig, PipelineStats
from persistence.vector.protocol.pipeline.callback import PipelineProgressCallback
from persistence.vector.implementation.domain.business import (
    BusinessChunkResult,
    BusinessQueryResult
)
from persistence.vector.implementation.domain.engine import EngineVectorItem

if TYPE_CHECKING:
    from persistence.vector.protocol.vector_transaction import BaseVectorTransactionManager


class SyncVectorPipelineProtocol(BaseVectorPipeline):
    def __init__(
        self,
        embedder,
        storage,
        id_generator,
        searcher=None,
        chunker=None,
        transaction_manager: Optional["BaseVectorTransactionManager"] = None,
        config: Optional[PipelineConfig] = None,
        callbacks: Optional[list[PipelineProgressCallback]] = None
    ):
        super().__init__(
            embedder=embedder,
            storage=storage,
            id_generator=id_generator,
            searcher=searcher,
            chunker=chunker,
            transaction_manager=transaction_manager,
            config=config,
            callbacks=callbacks
        )
        self._validate()

    @abstractmethod
    def create_searcher(self):
        pass

    @abstractmethod
    def ingest(self, chunks: list[BusinessChunkResult]) -> int:
        pass

    def ingest_documents(
        self,
        documents: list[tuple[str, dict[str, Any]]],
        chunk_size: Optional[int] = None,
        chunk_overlap: int = 0
    ) -> int:
        if self._chunker is None:
            raise ValueError("Cannot ingest raw documents without a chunker configured")
        
        all_chunks = []
        for content, metadata in documents:
            chunks = self._chunker.chunk(content, metadata)
            all_chunks.extend(chunks)
        
        return self.ingest(all_chunks)

    @abstractmethod
    def search(
        self,
        query_text: str,
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[BusinessQueryResult]:
        pass

    def batch_search(
        self,
        query_texts: list[str],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[list[BusinessQueryResult]]:
        return [self.search(text, k, filter_metadata) for text in query_texts]

    def delete(self, ids: list[str]) -> int:
        deleted = self._storage.delete_vectors(ids)
        self._stats.total_deleted += deleted
        return deleted

    def update(self, items: list[EngineVectorItem]) -> int:
        updated = self._storage.update_vectors(items)
        self._stats.total_updated += updated
        return updated

    def get(self, ids: list[str]) -> list[EngineVectorItem]:
        return self._storage.get_vectors(ids)

    def count(self) -> int:
        return self._storage.count

    def save(self, path: str) -> None:
        self._storage.save(path)

    def load(self, path: str) -> None:
        self._storage.load(path)

    def clear(self) -> int:
        all_items = self._storage.get_vectors([])
        if all_items:
            ids = [item.id for item in all_items]
            return self._storage.delete_vectors(ids)
        return 0

    def _embed_chunks(self, chunks: list[BusinessChunkResult]) -> list[EngineVectorItem]:
        return self._embedder.embed_chunks(chunks)

    def _chunk_documents(self, documents: str, metadata: dict[str, Any] | None = None) -> list[BusinessChunkResult]:
        if self._chunker is None:
            raise ValueError("Cannot chunk documents without a chunker configured")
        return self._chunker.chunk(documents, metadata)