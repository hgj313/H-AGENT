"""
事务协议模块 - 遵循DIP依赖倒置原则

所有数据库事务实现都必须依赖于本模块定义的抽象协议，
顶层协议不依赖任何具体数据库实现。

模块结构：
├── base.py          # 核心事务抽象（事务、事务管理器基类）
└── __init__.py      # 模块导出

注意：具体的向量/关系型事务协议已下沉到对应域：
- vector/protocol/vector_transaction.py
- relational/protocol/relational_transaction.py
"""

from persistence.protocols.transaction.base import (
    TransactionState,
    IsolationLevel,
    TransactionOptions,
    TransactionResult,
    BaseTransaction,
    BaseTransactionManager,
)


__all__ = [
    "TransactionState",
    "IsolationLevel",
    "TransactionOptions",
    "TransactionResult",
    "BaseTransaction",
    "BaseTransactionManager",
]