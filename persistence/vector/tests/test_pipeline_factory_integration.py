import pytest
import logging
from persistence.vector.implementation.pipeline_factory_deprecated import PipelineFactory
from persistence.vector.implementation.dependency_resolver import AdaptationWarning


class TestPipelineFactoryIntegration:

    def test_create_with_only_storage_type(self):
        pipeline = PipelineFactory.create(store_type="chroma")

        assert pipeline.storage is not None
        assert pipeline.searcher is not None

    def test_create_with_incompatible_combination_auto_fix(self, caplog):
        with caplog.at_level(logging.WARNING):
            pipeline = PipelineFactory.create(
                store_type="chroma",
                engine_type="milvus"
            )

        warning_logs = [r.message for r in caplog.records if "[AUTO]" in r.message]
        assert len(warning_logs) > 0
        assert "engine_type" in warning_logs[0]

        assert pipeline.storage is not None
        assert hasattr(pipeline, "_adaptation_warnings")
        assert len(pipeline._adaptation_warnings) > 0

    def test_create_with_all_explicit_compatible(self, caplog):
        with caplog.at_level(logging.WARNING):
            pipeline = PipelineFactory.create(
                store_type="chroma",
                engine_type="chroma",
                searcher_type="similarity",
                transaction_type="chroma"
            )

        warning_logs = [r.message for r in caplog.records if "[AUTO]" in r.message]
        assert len(warning_logs) == 0

    def test_async_pipeline_has_warnings(self, caplog):
        with caplog.at_level(logging.WARNING):
            pipeline = PipelineFactory.create(
                store_type="chroma",
                engine_type="milvus",
                enable_async=False
            )

        assert hasattr(pipeline, "_adaptation_warnings")
        assert len(pipeline._adaptation_warnings) > 0

    def test_adaptation_warnings_accessible(self):
        pipeline = PipelineFactory.create(
            store_type="chroma",
            engine_type="milvus"
        )

        assert hasattr(pipeline, "_adaptation_warnings")
        assert isinstance(pipeline._adaptation_warnings, list)
        assert all(isinstance(w, AdaptationWarning) for w in pipeline._adaptation_warnings)

    def test_similarity_searcher_is_default(self):
        pipeline = PipelineFactory.create(store_type="chroma")
        assert pipeline.searcher is not None

    def test_user_provided_searcher_preserved(self):
        from persistence.vector.implementation.query.similarity_searcher import SimilaritySearcher
        from persistence.vector.implementation.embedding import EmbedderFactory
        from persistence.vector.implementation.store import VectorStoreFactory

        embedder = EmbedderFactory.create("bge-m3")
        storage = VectorStoreFactory.create("chroma")
        user_searcher = SimilaritySearcher(embedder=embedder, storage=storage, search_engine=None)

        pipeline = PipelineFactory.create(
            store_type="chroma",
            embedder=embedder,
            storage=storage,
            searcher=user_searcher
        )

        assert isinstance(pipeline._searcher, SimilaritySearcher)
        assert pipeline._searcher._embedder is embedder
        assert pipeline._searcher._storage is storage
        assert len(pipeline._adaptation_warnings) == 0

    def test_transaction_manager_created_with_correct_type(self):
        pipeline = PipelineFactory.create(
            store_type="chroma",
            enable_transaction=True
        )

        if pipeline._transaction_manager is not None:
            tm_name = type(pipeline._transaction_manager).__name__
            assert "Chroma" in tm_name

    def test_no_warnings_when_user_specifies_same_as_inferred(self):
        pipeline = PipelineFactory.create(
            store_type="chroma",
            engine_type="chroma",
            searcher_type="similarity",
            transaction_type="chroma"
        )

        assert len(pipeline._adaptation_warnings) == 0