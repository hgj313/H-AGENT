"""
向量搜索引擎模块 - 与 store、query 平级的独立目录

目录结构：
├── engine/                    # 搜索引擎层
│   ├── __init__.py
│   ├── chroma_engine.py       # ChromaDB 搜索引擎实现
│   └── factory.py             # 搜索引擎工厂
├── query/                     # 自然语言查询层
├── store/                     # 存储层
└── protocols/                 # 协议定义
"""

from persistence.vector.implementation.engine.factory import SearchEngineFactory
from persistence.vector.implementation.engine.chroma_engine import ChromaSearchEngine

__all__ = ["ChromaSearchEngine", "SearchEngineFactory"]
