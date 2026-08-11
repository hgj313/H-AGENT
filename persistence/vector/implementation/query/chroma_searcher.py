"""
[DEPRECATED] 已合并到 list_based_searcher.py

请使用：
    from persistence.vector.implementation.query.list_based_searcher import ListBasedVectorSearcher
"""
from persistence.vector.implementation.query.list_based_searcher import ListBasedVectorSearcher as ChromaVectorSearcher  # noqa: F401

__all__ = ["ChromaVectorSearcher"]
