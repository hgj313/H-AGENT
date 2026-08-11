import logging
from typing import TYPE_CHECKING, Optional

from persistence.vector.protocol.pipeline import (
    SyncVectorPipelineProtocol,
    PipelineConfig,
)
from persistence.vector.protocol.embedding import BaseEmbedder
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.protocol.query import BaseVectorSearcher
from persistence.vector.protocol.chunker import BaseChunker
from persistence.vector.protocol.vector_transaction import BaseVectorTransactionManager
from persistence.vector.implementation.domain.id_generator import VectorIdGenerator
from persistence.vector.implementation.query.list_based_searcher import ListBasedVectorSearcher

if TYPE_CHECKING:
    from persistence.vector.implementation.domain.business import BusinessQueryResult


logger = logging.getLogger(__name__)


class VectorPipeline(SyncVectorPipelineProtocol):
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

    def create_searcher(self) -> BaseVectorSearcher:
        if self._searcher is None:
            self._searcher = ListBasedVectorSearcher(
                embedder=self.embedder,
                storage=self.storage
            )
        return self._searcher

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

    def batch_search(
        self,
        query_texts: list[str],
        k: int = 4,
        filter_metadata=None
    ) -> list[list["BusinessQueryResult"]]:
        return self.searcher.batch_search(query_texts, k=k, filter_metadata=filter_metadata)
