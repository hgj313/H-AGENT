"""
搜索引擎工厂 - 管理搜索引擎实例
"""
from typing import Optional

from persistence.vector.implementation.engine import ChromaSearchEngine


class SearchEngineFactory:
    """搜索引擎工厂"""
    
    _REGISTRY = {
        "chroma": ChromaSearchEngine,
    }

    @classmethod
    def create(
        cls,
        engine_type: str = "chroma",
        storage = None,
        **kwargs
    ):
        engine_cls = cls._REGISTRY.get(engine_type.lower())
        if engine_cls is None:
            raise ValueError(f"Unknown engine type: {engine_type}. Available: {list(cls._REGISTRY.keys())}")
        
        if storage is None:
            raise ValueError("storage parameter is required for QueryEngine creation")
        
        return engine_cls(storage=storage, **kwargs)

    @classmethod
    def register(cls, name: str, engine_cls: type) -> None:
        cls._REGISTRY[name.lower()] = engine_cls

    @classmethod
    def list_available(cls) -> list[str]:
        return list(cls._REGISTRY.keys())