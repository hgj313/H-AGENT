from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Any

from persistence.vector.protocol.pipeline.base_protocol import BaseVectorPipeline
from persistence.vector.protocol.pipeline.config import PipelineConfig
from persistence.vector.protocol.pipeline.callback import PipelineProgressCallback
from persistence.vector.implementation.domain.business import (
    BusinessChunkResult,
    BusinessQueryResult
)
from persistence.vector.implementation.domain.engine import EngineVectorItem

if TYPE_CHECKING:
    from persistence.vector.protocol.vector_transaction import BaseVectorTransactionManager


class AsyncVectorPipelineProtocol(BaseVectorPipeline):
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
    async def aingest(self, chunks: list[BusinessChunkResult]) -> int:
        pass

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

    @abstractmethod
    async def asearch(
        self,
        query_text: str,
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[BusinessQueryResult]:
        pass

    async def abatch_search(
        self,
        query_texts: list[str],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[list[BusinessQueryResult]]:
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

    async def aupdate(self, items: list[EngineVectorItem]) -> int:
        import asyncio
        loop = asyncio.get_event_loop()
        updated = await loop.run_in_executor(None, self._storage.update_vectors, items)
        self._stats.total_updated += updated
        return updated

    def _embed_chunks(self, chunks: list[BusinessChunkResult]) -> list[EngineVectorItem]:
        return self._embedder.embed_chunks(chunks)

    def _chunk_documents(self, documents: str, metadata: dict[str, Any] | None = None) -> list[BusinessChunkResult]:
        if self._chunker is None:
            raise ValueError("Cannot chunk documents without a chunker configured")
        return self._chunker.chunk(documents, metadata)