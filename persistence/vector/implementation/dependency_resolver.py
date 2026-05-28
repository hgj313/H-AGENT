from dataclasses import dataclass
from typing import Optional


@dataclass
class AdaptationWarning:
    level: str
    field: str
    original_value: any
    corrected_value: any
    reason: str
    component: str
    related_component: str

    def __str__(self) -> str:
        return (
            f"[{self.level}] {self.component}.{self.field} = '{self.original_value}' "
            f"is incompatible with {self.related_component}. "
            f"Auto-corrected to: '{self.corrected_value}'. "
            f"(Resolution: {self.reason})"
        )


class DependencyResolver:

    DEPENDENCY_RULES = {
        ("storage", "chroma"): {
            "compatible_engines": ["chroma"],
            "compatible_searchers": ["chroma", "similarity"],
            "compatible_transaction_managers": ["chroma"],
        },
        ("storage", "milvus"): {
            "compatible_engines": ["milvus"],
            "compatible_searchers": ["milvus"],
            "compatible_transaction_managers": ["milvus"],
        },
        ("storage", "qdrant"): {
            "compatible_engines": ["qdrant"],
            "compatible_searchers": ["qdrant"],
            "compatible_transaction_managers": ["qdrant"],
        },
        ("storage", "*"): {
            "compatible_engines": ["chroma"],
            "compatible_searchers": ["similarity"],
            "compatible_transaction_managers": ["chroma"],
        },
    }

    AUTO_INFER_RULES = {
        "chroma": {
            "engine_type": "chroma",
            "searcher_type": "similarity",
            "transaction_type": "chroma",
        },
        "milvus": {
            "engine_type": "milvus",
            "searcher_type": "milvus",
            "transaction_type": "milvus",
        },
        "qdrant": {
            "engine_type": "qdrant",
            "searcher_type": "qdrant",
            "transaction_type": "qdrant",
        },
        "*": {
            "engine_type": "chroma",
            "searcher_type": "similarity",
            "transaction_type": "chroma",
        },
    }

    def __init__(self):
        self._warnings: list[AdaptationWarning] = []

    @property
    def warnings(self) -> list[AdaptationWarning]:
        return list(self._warnings)

    def clear_warnings(self) -> None:
        self._warnings.clear()

    def resolve(self, config: dict) -> dict:
        self.clear_warnings()
        resolved = dict(config)

        resolved = self._auto_infer_from_storage_type(resolved)
        resolved = self._validate_engine_storage_compat(resolved)
        resolved = self._validate_searcher_engine_compat(resolved)
        resolved = self._validate_transaction_storage_compat(resolved)

        return resolved

    def _auto_infer_from_storage_type(self, config: dict) -> dict:
        storage_type = config.get("storage_type")
        if not storage_type:
            return config

        inferred = self.AUTO_INFER_RULES.get(
            storage_type,
            self.AUTO_INFER_RULES.get("*", {})
        )
        for target_field, inferred_value in inferred.items():
            if target_field not in config or config.get(target_field) is None:
                config[target_field] = inferred_value
        return config

    def _validate_engine_storage_compat(self, config: dict) -> dict:
        engine_type = config.get("engine_type")
        storage_type = config.get("storage_type")
        if not engine_type or not storage_type:
            return config

        rules = self.DEPENDENCY_RULES.get(
            ("storage", storage_type),
            self.DEPENDENCY_RULES[("storage", "*")]
        )
        compatible = rules.get("compatible_engines", [])

        if engine_type not in compatible:
            original = engine_type
            corrected = storage_type
            self._warnings.append(AdaptationWarning(
                level="AUTO",
                field="engine_type",
                original_value=original,
                corrected_value=corrected,
                reason="storage_type is the root — engine follows",
                component="search_engine",
                related_component=f"storage_type({storage_type})"
            ))
            config["engine_type"] = corrected

        return config

    def _validate_searcher_engine_compat(self, config: dict) -> dict:
        searcher_type = config.get("searcher_type")
        engine_type = config.get("engine_type")
        if not searcher_type or not engine_type:
            return config

        searcher_to_engine = {
            "chroma": "chroma",
            "similarity": "chroma",
            "milvus": "milvus",
            "qdrant": "qdrant",
        }
        expected_engine = searcher_to_engine.get(searcher_type)
        if expected_engine and expected_engine != engine_type:
            original = searcher_type
            corrected = engine_type
            self._warnings.append(AdaptationWarning(
                level="AUTO",
                field="searcher_type",
                original_value=original,
                corrected_value=corrected,
                reason=f"searcher '{searcher_type}' only supports engine '{expected_engine}', got '{engine_type}'",
                component="searcher",
                related_component=f"search_engine({engine_type})"
            ))
            config["searcher_type"] = corrected

        return config

    def _validate_transaction_storage_compat(self, config: dict) -> dict:
        transaction_type = config.get("transaction_type")
        storage_type = config.get("storage_type")
        if not transaction_type or not storage_type:
            return config

        rules = self.DEPENDENCY_RULES.get(
            ("storage", storage_type),
            self.DEPENDENCY_RULES[("storage", "*")]
        )
        compatible = rules.get("compatible_transaction_managers", [])

        if transaction_type not in compatible:
            original = transaction_type
            corrected = compatible[0] if compatible else "chroma"
            self._warnings.append(AdaptationWarning(
                level="AUTO",
                field="transaction_type",
                original_value=original,
                corrected_value=corrected,
                reason=f"transaction manager '{transaction_type}' incompatible with storage_type '{storage_type}'",
                component="transaction_manager",
                related_component=f"storage_type({storage_type})"
            ))
            config["transaction_type"] = corrected

        return config