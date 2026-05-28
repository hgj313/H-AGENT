from typing import Optional

from persistence.vector.implementation.embedding import EmbedderFactory
from persistence.vector.implementation.store import VectorStoreFactory
from persistence.vector.implementation.engine import ChromaSearchEngine
from persistence.vector.implementation.pipeline import VectorPipeline, AsyncVectorPipeline
from persistence.vector.implementation.transaction import TransactionManagerFactory
from persistence.vector.implementation.domain.id_generator import VectorIdGenerator
from persistence.vector.protocol import (
    BaseEmbedder,
    BaseVectorSearcher,
    BaseVectorStorage,
    BaseSearchEngine,
    BaseChunker,
    BaseVectorTransactionManager,
    PipelineConfig,
)
from persistence.vector.implementation.chunker import GeneralChunker


class PipelineFactory:
    @classmethod
    def create(
        cls,
        embedder: Optional[BaseEmbedder] = None,
        storage: Optional[BaseVectorStorage] = None,
        id_generator: Optional[VectorIdGenerator] = None,
        chunker: Optional[BaseChunker] = None,
        searcher: Optional[BaseVectorSearcher] = None,
        search_engine: Optional[BaseSearchEngine] = None,
        transaction_manager: Optional[BaseVectorTransactionManager] = None,
        embedder_type: str = "bge-m3",
        store_type: str = "chroma",
        enable_transaction: bool = True,
        embedder_kwargs: Optional[dict] = None,
        store_kwargs: Optional[dict] = None,
        chunker_kwargs: Optional[dict] = None,
        pipeline_config: Optional[PipelineConfig] = None,
        enable_async: bool = False
    ) -> VectorPipeline:
        if embedder is None:
            embedder_kwargs = embedder_kwargs or {}
            embedder = EmbedderFactory.create(embedder_type, **embedder_kwargs)

        if storage is None:
            store_kwargs = store_kwargs or {}
            store_kwargs.setdefault("dimension", embedder.dimension)
            storage = VectorStoreFactory.create(store_type, **store_kwargs)

        if chunker is None:
            chunker_kwargs = chunker_kwargs or {}
            chunker = GeneralChunker(**chunker_kwargs)
        

        if searcher is None:
            if search_engine is None:
                search_engine = ChromaSearchEngine(storage)
            else:
                pass
            searcher = BaseVectorSearcher(search_engine)
            

        if transaction_manager is None and enable_transaction:
            transaction_manager = TransactionManagerFactory.create(storage, store_type)

        if enable_async:
            return AsyncVectorPipeline(
                embedder=embedder,
                storage=storage,
                searcher=searcher,
                search_engine=search_engine,
                id_generator=id_generator,
                chunker=chunker,
                transaction_manager=transaction_manager,
                config=pipeline_config
            )
        else:
            return VectorPipeline(
                embedder=embedder,
                storage=storage,
                id_generator=id_generator,
                chunker=chunker,
                transaction_manager=transaction_manager,
                config=pipeline_config
            )