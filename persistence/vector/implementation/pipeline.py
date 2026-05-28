import logging
from typing import TYPE_CHECKING, Optional

from persistence.vector.protocol.pipeline import (
    BaseVectorPipeline,
    AsyncBaseVectorPipeline,
    PipelineConfig,
)
from persistence.vector.protocol.embedding import BaseEmbedder
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.protocol.query import BaseVectorSearcher
from persistence.vector.protocol.chunker import BaseChunker
from persistence.vector.protocol.vector_transaction import BaseVectorTransactionManager
from persistence.vector.implementation.domain.id_generator import VectorIdGenerator
from persistence.vector.implementation.query.similarity_searcher import SimilaritySearcher

if TYPE_CHECKING:
    from persistence.vector.protocol.query import QueryResult

logger = logging.getLogger(__name__)


class VectorPipeline(BaseVectorPipeline):
    def __init__(
        self,
        embedder: BaseEmbedder,
        storage: BaseVectorStorage,
        id_generator: VectorIdGenerator,
        searcher: Optional[BaseVectorSearcher] = None,
        chunker: Optional[BaseChunker] = None,
        transaction_manager: Optional[BaseVectorTransactionManager] = None,
        config: Optional[PipelineConfig] = None
    ):
        super().__init__(
            embedder=embedder,
            storage=storage,
            id_generator=id_generator,
            searcher=searcher,
            chunker=chunker,
            transaction_manager=transaction_manager,
            config=config
        )
        self._internal_searcher: Optional[BaseVectorSearcher] = searcher

    def create_searcher(self) -> BaseVectorSearcher:
        if self._internal_searcher is None:
            self._internal_searcher = SimilaritySearcher(
                embedder=self.embedder,
                storage=self.storage
            )
        return self._internal_searcher

    def ingest(self, chunks) -> int:
        items = self._embed_chunks(chunks)

        if self._transaction_manager is not None:
            tx = self._transaction_manager.begin()
            try:
                tx.add_vectors(items)
                result = tx.commit()
                if not result.success:
                    raise RuntimeError(f"Transaction failed: {result.message}")
            except Exception as e:
                if self._transaction_manager.is_in_transaction:
                    self._transaction_manager.rollback(str(e))
                raise
        else:
            self._storage.add_vectors(items)

        self._stats.total_ingested += len(items)
        return len(items)

    def search(
        self,
        query_text: str,
        k: int = 4,
        filter_metadata=None
    ) -> list["QueryResult"]:
        searcher = self.searcher
        return searcher.search(query_text, k, filter_metadata)

    def batch_search(
        self,
        query_texts: list[str],
        k: int = 4,
        filter_metadata=None
    ) -> list[list["QueryResult"]]:
        return [self.search(text, k, filter_metadata) for text in query_texts]


class AsyncVectorPipeline(AsyncBaseVectorPipeline):
    def __init__(
        self,
        embedder: BaseEmbedder,
        storage: BaseVectorStorage,
        id_generator: VectorIdGenerator,
        searcher: Optional[BaseVectorSearcher] = None,
        chunker: Optional[BaseChunker] = None,
        transaction_manager: Optional[BaseVectorTransactionManager] = None,
        config: Optional[PipelineConfig] = None
    ):
        super().__init__(
            embedder=embedder,
            storage=storage,
            id_generator=id_generator,
            searcher=searcher,
            chunker=chunker,
            transaction_manager=transaction_manager,
            config=config
        )
        self._internal_searcher: Optional[BaseVectorSearcher] = searcher

    def create_searcher(self) -> BaseVectorSearcher:
        if self._internal_searcher is None:
            self._internal_searcher = SimilaritySearcher(
                embedder=self.embedder,
                storage=self.storage
            )
        return self._internal_searcher

    def search(
        self,
        query_text: str,
        k: int = 4,
        filter_metadata=None
    ) -> list["QueryResult"]:
        searcher = self.searcher
        return searcher.search(query_text, k, filter_metadata)

    async def aingest(self, chunks) -> int:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.ingest, chunks)