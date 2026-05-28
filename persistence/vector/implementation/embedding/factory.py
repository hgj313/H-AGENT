import os
from typing import Optional

from persistence.vector.implementation.embedding.bge_m3 import BgeM3Embedder
from persistence.vector.protocol.embedding import BaseEmbedder


class EmbedderFactory:
    _REGISTRY = {
        "bge-m3": BgeM3Embedder,
    }

    @classmethod
    def create(
        cls,
        name: str,
        model_name_or_path: Optional[str] = None,
        device: Optional[str] = None,
        normalize_embeddings: bool = True,
        **kwargs
    ) -> BaseEmbedder:
        embedder_cls = cls._REGISTRY.get(name.lower())
        if embedder_cls is None:
            raise ValueError(f"Unknown embedder: {name}. Available: {list(cls._REGISTRY.keys())}")
        return embedder_cls(
            model_name_or_path=model_name_or_path,
            device=device,
            normalize_embeddings=normalize_embeddings,
            **kwargs
        )

    @classmethod
    def register(cls, name: str, embedder_cls: type) -> None:
        cls._REGISTRY[name.lower()] = embedder_cls

    @classmethod
    def list_available(cls) -> list[str]:
        return list(cls._REGISTRY.keys())