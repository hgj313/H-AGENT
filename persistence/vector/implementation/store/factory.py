"""
存储层工厂 - 管理存储实例
"""
from persistence.vector.implementation.store.chroma_storage import ChromaVectorStorage


class VectorStoreFactory:
    """向量存储工厂"""
    
    _REGISTRY = {
        "chroma": ChromaVectorStorage,
    }

    @classmethod
    def create(
        cls,
        store_type: str = "chroma",
        dimension: int = 1024,
        **kwargs
    ):
        store_cls = cls._REGISTRY.get(store_type.lower())
        if store_cls is None:
            raise ValueError(f"Unknown store type: {store_type}. Available: {list(cls._REGISTRY.keys())}")
        return store_cls(dimension=dimension, **kwargs)

    @classmethod
    def register(cls, name: str, store_cls: type) -> None:
        cls._REGISTRY[name.lower()] = store_cls

    @classmethod
    def list_available(cls) -> list[str]:
        return list(cls._REGISTRY.keys())