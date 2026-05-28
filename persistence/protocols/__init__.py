"""
持久化层协议模块 - 遵循DIP依赖倒置原则

所有具体实现都必须依赖于本模块定义的抽象协议，
顶层协议不依赖任何具体数据库实现。
"""

from typing import TYPE_CHECKING

from persistence.protocols.transaction.base import (
    TransactionState,
    IsolationLevel,
    TransactionOptions,
    TransactionResult,
    BaseTransaction,
    BaseTransactionManager,
)

if TYPE_CHECKING:
    from persistence.vector.protocol import (
        VectorStorageConnection,
        BaseVectorTransaction,
        BaseVectorTransactionManager,
    )

    from persistence.relational.protocol import (
        SQLDialect,
        RelationalConnection,
        BaseRelationalTransaction,
        BaseRelationalTransactionManager,
    )


__all__ = [
    "TransactionState",
    "IsolationLevel",
    "TransactionOptions",
    "TransactionResult",
    "BaseTransaction",
    "BaseTransactionManager",
    "VectorStorageConnection",
    "BaseVectorTransaction",
    "BaseVectorTransactionManager",
    "SQLDialect",
    "RelationalConnection",
    "BaseRelationalTransaction",
    "BaseRelationalTransactionManager",
]