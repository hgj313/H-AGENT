"""
已废弃，使用pipeline文件夹下的新版本同步或异步工厂
"""

import logging
from typing import Optional

from persistence.vector.implementation.dependency_resolver import DependencyResolver, AdaptationWarning
from persistence.vector.implementation.embedding import EmbedderFactory
from persistence.vector.implementation.store import VectorStoreFactory
from persistence.vector.implementation.engine import ChromaSearchEngine
from persistence.vector.implementation.engine.factory import SearchEngineFactory as EngineFactory
from persistence.vector.implementation.query.chroma_searcher import ChromaVectorSearcher
from persistence.vector.implementation.query.similarity_searcher import SimilaritySearcher
from persistence.vector.implementation.pipeline_deprecated import VectorPipeline, AsyncVectorPipeline
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

logger = logging.getLogger(__name__)


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
        engine_type: Optional[str] = None,
        searcher_type: Optional[str] = None,
        transaction_type: Optional[str] = None,
        enable_transaction: bool = True,
        embedder_kwargs: Optional[dict] = None,
        store_kwargs: Optional[dict] = None,
        chunker_kwargs: Optional[dict] = None,
        pipeline_config: Optional[PipelineConfig] = None,
        enable_async: bool = False
    ) -> VectorPipeline:
        raw_config = {
            "embedder": embedder,
            "storage": storage,
            "chunker": chunker,
            "searcher": searcher,
            "search_engine": search_engine,
            "transaction_manager": transaction_manager,
            "embedder_type": embedder_type,
            "storage_type": store_type,
            "engine_type": engine_type,
            "searcher_type": searcher_type,
            "transaction_type": transaction_type,
            "enable_async": enable_async,
            "enable_transaction": enable_transaction,
        }

        resolver = DependencyResolver()
        resolved = resolver.resolve(raw_config)

        for warning in resolver.warnings:
            logger.warning(str(warning))
            print(warning)

        embedder = resolved["embedder"]
        storage = resolved["storage"]
        chunker = resolved["chunker"]
        searcher = resolved["searcher"]
        search_engine = resolved["search_engine"]
        transaction_manager = resolved["transaction_manager"]
        engine_type_resolved = resolved.get("engine_type")
        searcher_type_resolved = resolved.get("searcher_type")
        transaction_type_resolved = resolved.get("transaction_type")

        if embedder is None:
            embedder_kwargs = embedder_kwargs or {}
            embedder = EmbedderFactory.create(resolved["embedder_type"], **embedder_kwargs)

        if storage is None:
            store_kwargs = store_kwargs or {}
            store_kwargs.setdefault("dimension", embedder.dimension)
            storage = VectorStoreFactory.create(resolved["storage_type"], **store_kwargs)

        if chunker is None:
            chunker_kwargs = chunker_kwargs or {}
            chunker = GeneralChunker(**chunker_kwargs)

        if searcher is None:
            if search_engine is None and engine_type_resolved:
                storage_cls_name = type(storage).__name__
                if "Chroma" in storage_cls_name:
                    search_engine = ChromaSearchEngine(storage)
                elif "Milvus" in storage_cls_name:
                    try:
                        from persistence.vector.implementation.engine.milvus_engine import MilvusSearchEngine
                        search_engine = MilvusSearchEngine(storage)
                    except ImportError:
                        search_engine = ChromaSearchEngine(storage)
                elif "Qdrant" in storage_cls_name:
                    try:
                        from persistence.vector.implementation.engine.qdrant_engine import QdrantSearchEngine
                        search_engine = QdrantSearchEngine(storage)
                    except ImportError:
                        search_engine = ChromaSearchEngine(storage)
                else:
                    search_engine = ChromaSearchEngine(storage)

            if searcher_type_resolved == "similarity":
                searcher = SimilaritySearcher(
                    embedder=embedder,
                    storage=storage,
                    search_engine=search_engine
                )
            elif searcher_type_resolved == "chroma":
                searcher = ChromaVectorSearcher(
                    embedder=embedder,
                    storage=storage,
                    search_engine=search_engine
                )
            elif searcher_type_resolved == "milvus":
                try:
                    from persistence.vector.implementation.query.milvus_searcher import MilvusVectorSearcher
                    searcher = MilvusVectorSearcher(
                        embedder=embedder,
                        storage=storage,
                        search_engine=search_engine
                    )
                except ImportError:
                    searcher = SimilaritySearcher(
                        embedder=embedder,
                        storage=storage,
                        search_engine=search_engine
                    )
            elif searcher_type_resolved == "qdrant":
                try:
                    from persistence.vector.implementation.query.qdrant_searcher import QdrantVectorSearcher
                    searcher = QdrantVectorSearcher(
                        embedder=embedder,
                        storage=storage,
                        search_engine=search_engine
                    )
                except ImportError:
                    searcher = SimilaritySearcher(
                        embedder=embedder,
                        storage=storage,
                        search_engine=search_engine
                    )
            else:
                searcher = SimilaritySearcher(
                    embedder=embedder,
                    storage=storage,
                    search_engine=search_engine
                )

        if transaction_manager is None and resolved.get("enable_transaction"):
            tm_type = transaction_type_resolved or resolved["storage_type"]
            transaction_manager = TransactionManagerFactory.create(storage, tm_type)

        if enable_async:
            pipeline = AsyncVectorPipeline(
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
            pipeline = VectorPipeline(
                embedder=embedder,
                storage=storage,
                searcher=searcher,
                id_generator=id_generator,
                chunker=chunker,
                transaction_manager=transaction_manager,
                config=pipeline_config
            )

        pipeline._adaptation_warnings = resolver.warnings
        return pipeline