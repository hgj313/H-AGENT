from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Any, Callable
from typing_extensions import Self

from persistence.vector.implementation.domain.ChunkResult import ChunkResult
from persistence.vector.implementation.domain.QueryResult import QueryResult
from persistence.vector.implementation.domain.VectorItem import VectorItem
from persistence.vector.implementation.domain.id_generator import VectorIdGenerator
from persistence.vector.protocol.embedding import BaseEmbedder
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.vector.protocol.query import BaseVectorSearcher
from persistence.vector.protocol.chunker import BaseChunker

if TYPE_CHECKING:
    from persistence.vector.protocol.vector_transaction import BaseVectorTransactionManager


class PipelineConfig:
    def __init__(
        self,
        enable_async: bool = True,
        enable_transaction: bool = True,
        enable_batch: bool = True,
        batch_size: int = 100,
        validate_dimension: bool = True,
        allow_duplicates: bool = False,
        max_retry: int = 3,
        retry_delay: float = 0.5
    ):
        self.enable_async = enable_async
        self.enable_transaction = enable_transaction
        self.enable_batch = enable_batch
        self.batch_size = batch_size
        self.validate_dimension = validate_dimension
        self.allow_duplicates = allow_duplicates
        self.max_retry = max_retry
        self.retry_delay = retry_delay


class PipelineStats:
    def __init__(self):
        self.total_ingested = 0
        self.total_searched = 0
        self.total_deleted = 0
        self.total_updated = 0
        self.failed_operations = 0
        self.last_operation_time: Optional[float] = None


class PipelineProgressCallback(ABC):
    @abstractmethod
    def on_ingest_start(self, total_chunks: int) -> None:
        pass

    @abstractmethod
    def on_ingest_progress(self, processed: int, total: int) -> None:
        pass

    @abstractmethod
    def on_ingest_complete(self, total_ingested: int) -> None:
        pass

    @abstractmethod
    def on_error(self, error: Exception, operation: str) -> None:
        pass


class BaseVectorPipeline(ABC):
    def __init__(
        self,
        embedder: BaseEmbedder,
        storage: BaseVectorStorage,
        id_generator: VectorIdGenerator,
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
        self._validate()

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

    @abstractmethod
    def create_searcher(self) -> BaseVectorSearcher:
        pass

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

    @abstractmethod
    def ingest(self, chunks: list[ChunkResult]) -> int:
        """摄入向量，必须包含向量化 + 存储逻辑"""
        pass

    def ingest_documents(
        self,
        documents: list[tuple[str, dict[str, Any]]],
        chunk_size: Optional[int] = None,
        chunk_overlap: int = 0
    ) -> int:
        """
        摄入原始文档。

        内部流程：
        1. 使用 chunker 将文档切分为 chunks
        2. 调用 ingest 方法完成向量化 + 存储

        子类可通过覆盖 ingest 或此方法来自定义行为。
        chunk_size 和 chunk_overlap 参数仅为接口兼容性存在，
        实际切分参数由配置的 chunker 决定。

        Args:
            documents: 待摄入的文档列表，元素为 (文本内容, 元数据) 元组
            chunk_size: 切分块大小（默认实现中不使用）
            chunk_overlap: 切分重叠大小（默认实现中不使用）

        Returns:
            实际摄入的 chunks 数量
        """
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
    ) -> list[QueryResult]:
        pass

    def batch_search(
        self,
        query_texts: list[str],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[list[QueryResult]]:
        return [self.search(text, k, filter_metadata) for text in query_texts]

    def delete(self, ids: list[str]) -> int:
        deleted = self._storage.delete_vectors(ids)
        self._stats.total_deleted += deleted
        return deleted

    def update(self, items: list[VectorItem]) -> int:
        updated = self._storage.update_vectors(items)
        self._stats.total_updated += updated
        return updated

    def get(self, ids: list[str]) -> list[VectorItem]:
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

    def _embed_content(self, content: str, metadata: dict[str, Any] | None = None) -> list[VectorItem]:
        if self._chunker is None:
            raise ValueError("Cannot embed content without a chunker configured")
        chunks = self._chunker.chunk(content, metadata)
        if hasattr(self._embedder, 'embed_chunks'):
            return self._embedder.embed_chunks(chunks)
        else:
            texts = [c.content for c in chunks]
            vectors = self._embedder.embed_documents(texts)
            return [
                VectorItem(
                    id=self._id_generator.generate(chunk.content),
                    content=chunk.content,
                    vector=vector,
                    metadata=chunk.metadata,
                    chunk_index=chunk.chunk_index,
                    chunk_type=chunk.chunk_type
                )
                for chunk, vector in zip(chunks, vectors)
            ]
    def _embed_chunks(self, chunks: list[ChunkResult]) -> list[VectorItem]:
        if hasattr(self._embedder, 'embed_chunks'):
            return self._embedder.embed_chunks(chunks)
        else:
            texts = [c.content for c in chunks]
            vectors = self._embedder.embed_documents(texts)
            return [
                VectorItem(
                    id=self._id_generator.generate(chunk.content),
                    content=chunk.content,
                    vector=vector,
                    metadata=chunk.metadata,
                    chunk_index=chunk.chunk_index,
                    chunk_type=chunk.chunk_type
                )
                for chunk, vector in zip(chunks, vectors)
            ]

    def _chunk_documents(self, documents: str, metadata: dict[str, Any] | None = None) -> list[ChunkResult]:
        if self._chunker is None:
            raise ValueError("Cannot chunk documents without a chunker configured")
        return self._chunker.chunk(documents, metadata)

    
    def reset_stats(self) -> None:
        self._stats = PipelineStats()

    def add_callback(self, callback: PipelineProgressCallback) -> None:
        self._callbacks.append(callback)

    def remove_callback(self, callback: PipelineProgressCallback) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify_error(self, error: Exception, operation: str) -> None:
        self._stats.failed_operations += 1
        for callback in self._callbacks:
            try:
                callback.on_error(error, operation)
            except Exception:
                pass


class AsyncBaseVectorPipeline(BaseVectorPipeline):
    async def aingest(self, chunks: list[ChunkResult]) -> int:
        items = self._embed_chunks(chunks)
        self._stats.total_ingested += len(items)
        return len(items)

    async def aingest_documents(
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
        
        return await self.aingest(all_chunks)

    async def asearch(
        self,
        query_text: str,
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[QueryResult]:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.search, query_text, k, filter_metadata)

    async def abatch_search(
        self,
        query_texts: list[str],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[list[QueryResult]]:
        import asyncio
        return await asyncio.gather(*[
            self.asearch(text, k, filter_metadata) for text in query_texts
        ])

    async def adelete(self, ids: list[str]) -> int:
        import asyncio
        loop = asyncio.get_event_loop()
        deleted = await loop.run_in_executor(None, self._storage.delete_vectors, ids)
        self._stats.total_deleted += deleted
        return deleted

    async def aupdate(self, items: list[VectorItem]) -> int:
        import asyncio
        loop = asyncio.get_event_loop()
        updated = await loop.run_in_executor(None, self._storage.update_vectors, items)
        self._stats.total_updated += updated
        return updated