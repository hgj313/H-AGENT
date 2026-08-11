import pytest
from persistence.vector.implementation.dependency_resolver import DependencyResolver, AdaptationWarning


class TestDependencyResolver:

    def test_auto_infer_from_storage_type_chroma(self):
        resolver = DependencyResolver()
        config = {"storage_type": "chroma"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "chroma"
        assert resolved["searcher_type"] == "similarity"
        assert resolved["transaction_type"] == "chroma"
        assert len(resolver.warnings) == 0

    def test_auto_infer_from_storage_type_milvus(self):
        resolver = DependencyResolver()
        config = {"storage_type": "milvus"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "milvus"
        assert resolved["searcher_type"] == "milvus"
        assert resolved["transaction_type"] == "milvus"

    def test_auto_infer_from_storage_type_qdrant(self):
        resolver = DependencyResolver()
        config = {"storage_type": "qdrant"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "qdrant"
        assert resolved["searcher_type"] == "qdrant"
        assert resolved["transaction_type"] == "qdrant"

    def test_conflict_engine_storage_auto_correct(self):
        resolver = DependencyResolver()
        config = {"storage_type": "milvus", "engine_type": "chroma"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "milvus"
        assert len(resolver.warnings) == 1
        assert resolver.warnings[0].level == "AUTO"
        assert resolver.warnings[0].original_value == "chroma"
        assert resolver.warnings[0].corrected_value == "milvus"

    def test_conflict_transaction_storage_auto_correct(self):
        resolver = DependencyResolver()
        config = {"storage_type": "milvus", "transaction_type": "chroma"}
        resolved = resolver.resolve(config)

        assert resolved["transaction_type"] == "milvus"
        warning = resolver.warnings[0]
        assert warning.level == "AUTO"
        assert "transaction_manager" in warning.component

    def test_no_warnings_when_all_compatible(self):
        resolver = DependencyResolver()
        config = {
            "storage_type": "chroma",
            "engine_type": "chroma",
            "searcher_type": "similarity",
            "transaction_type": "chroma"
        }
        resolved = resolver.resolve(config)
        assert len(resolver.warnings) == 0

    def test_multiple_warnings_accumulated(self):
        resolver = DependencyResolver()
        config = {
            "storage_type": "milvus",
            "engine_type": "chroma",
            "transaction_type": "chroma"
        }
        resolved = resolver.resolve(config)

        assert len(resolver.warnings) == 2
        warning_fields = {w.field for w in resolver.warnings}
        assert "engine_type" in warning_fields
        assert "transaction_type" in warning_fields

    def test_explicit_config_preserved_when_no_conflict(self):
        resolver = DependencyResolver()
        config = {"storage_type": "chroma", "engine_type": "chroma"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "chroma"
        assert len(resolver.warnings) == 0

    def test_unknown_storage_type_uses_default_rules(self):
        resolver = DependencyResolver()
        config = {"storage_type": "unknown_store"}
        resolved = resolver.resolve(config)

        assert resolved["engine_type"] == "chroma"
        assert resolved["transaction_type"] == "chroma"

    def test_user_provided_instance_preserved(self):
        resolver = DependencyResolver()
        mock_storage = object()
        config = {
            "storage_type": "milvus",
            "storage": mock_storage,
            "engine_type": "chroma"
        }
        resolved = resolver.resolve(config)

        assert resolved["storage"] is mock_storage
        assert resolved["engine_type"] == "milvus"
        assert len(resolver.warnings) == 1

    def test_searcher_type_compat_check(self):
        resolver = DependencyResolver()
        config = {
            "storage_type": "chroma",
            "engine_type": "chroma",
            "searcher_type": "milvus"
        }
        resolved = resolver.resolve(config)

        assert resolved["searcher_type"] == "chroma"
        warning = resolver.warnings[0]
        assert warning.field == "searcher_type"
        assert warning.original_value == "milvus"
        assert warning.corrected_value == "chroma"

    def test_warning_str_format(self):
        resolver = DependencyResolver()
        config = {"storage_type": "milvus", "engine_type": "chroma"}
        resolver.resolve(config)

        warning = resolver.warnings[0]
        warning_str = str(warning)
        assert "[AUTO]" in warning_str
        assert "engine_type" in warning_str
        assert "milvus" in warning_str
        assert "chroma" in warning_str

    def test_clear_warnings(self):
        resolver = DependencyResolver()
        config = {"storage_type": "milvus", "engine_type": "chroma"}
        resolver.resolve(config)

        assert len(resolver.warnings) == 1

        resolver.clear_warnings()
        assert len(resolver.warnings) == 0

    def test_warnings_property_returns_copy(self):
        resolver = DependencyResolver()
        config = {"storage_type": "milvus"}
        resolver.resolve(config)

        warnings1 = resolver.warnings
        warnings2 = resolver.warnings

        assert warnings1 is not warnings2
        assert warnings1 == warnings2