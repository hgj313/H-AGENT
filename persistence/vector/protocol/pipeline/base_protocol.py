from typing import TYPE_CHECKING, Optional

from persistence.vector.protocol.embedding import BaseEmbedder
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.protocol.query import BaseVectorSearcher
from persistence.vector.protocol.chunker import BaseChunker
from persistence.vector.protocol.pipeline.config import PipelineConfig, PipelineStats
from persistence.vector.protocol.pipeline.callback import PipelineProgressCallback


if TYPE_CHECKING:
    from persistence.vector.protocol.vector_transaction import BaseVectorTransactionManager


class BaseVectorPipeline:
    def __init__(
        self,
        embedder: BaseEmbedder,
        storage: BaseVectorStorage,
        id_generator,
        searcher: Optional[BaseVectorSearcher] = None,
        chunker: Optional[BaseChunker] = None,
        transaction_manager: Optional["BaseVectorTransactionManager"] = None,
        config: Optional[PipelineConfig] = None,
        callbacks: Optional[list[PipelineProgressCallback]] = None
    ):
        self._embedder = embedder
        self._storage = storage
        self._id_generator = id_generator
        self._searcher = searcher
        self._chunker = chunker
        self._transaction_manager = transaction_manager
        self._config = config or PipelineConfig()
        self._callbacks = callbacks or []
        self._stats = PipelineStats()

    @property
    def embedder(self) -> BaseEmbedder:
        return self._embedder

    @property
    def storage(self) -> BaseVectorStorage:
        return self._storage

    @property
    def searcher(self) -> BaseVectorSearcher:
        if self._searcher is None:
            self._searcher = self.create_searcher()
        return self._searcher

    @property
    def chunker(self) -> Optional[BaseChunker]:
        return self._chunker

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def stats(self) -> PipelineStats:
        return self._stats

    def create_searcher(self) -> BaseVectorSearcher:
        raise NotImplementedError("Subclass must implement create_searcher")

    def _validate(self) -> None:
        if self._config.validate_dimension:
            expected_dim = self._storage.dimension
            if hasattr(self._embedder, 'dimension'):
                actual_dim = self._embedder.dimension
                if actual_dim != expected_dim:
                    raise ValueError(
                        f"Dimension mismatch: embedder outputs {actual_dim}D "
                        f"but storage expects {expected_dim}D"
                    )

    def _notify_error(self, error: Exception, operation: str) -> None:
        self._stats.failed_operations += 1
        for callback in self._callbacks:
            try:
                callback.on_error(error, operation)
            except Exception:
                pass

    def reset_stats(self) -> None:
        self._stats = PipelineStats()

    def add_callback(self, callback: PipelineProgressCallback) -> None:
        self._callbacks.append(callback)

    def remove_callback(self, callback: PipelineProgressCallback) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)