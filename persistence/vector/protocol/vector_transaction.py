from abc import ABC, abstractmethod
from typing import Optional, Any, Protocol, runtime_checkable

from persistence.vector.implementation.domain.engine import EngineVectorItem
from persistence.protocols.transaction.base import (
    BaseTransaction,
    BaseTransactionManager,
    TransactionOptions,
    TransactionResult,
)


@runtime_checkable
class VectorStorageConnection(Protocol):
    """向量数据库连接接口"""

    @property
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...


class BaseVectorTransaction(BaseTransaction):
    """向量数据库事务抽象协议"""

    @property
    @abstractmethod
    def storage_connection(self) -> VectorStorageConnection:
        pass

    @abstractmethod
    def add_vectors(self, items: list[EngineVectorItem]) -> bool:
        pass

    @abstractmethod
    def delete_vectors(self, ids: list[str]) -> bool:
        pass

    @abstractmethod
    def update_vectors(self, items: list[EngineVectorItem]) -> bool:
        pass

    @abstractmethod
    def batch_search(
        self,
        query_vectors: list[list[float]],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[list[tuple[EngineVectorItem, float]]]:
        """事务内批量检索（统一入口）

        Returns:
            list[list[(EngineVectorItem, score)]]，外层 index 对应 query
        """
        pass


class BaseVectorTransactionManager(BaseTransactionManager):
    """向量数据库事务管理器抽象协议"""

    @property
    @abstractmethod
    def storage_backend(self) -> str:
        pass

    @property
    @abstractmethod
    def supports_native_transactions(self) -> bool:
        pass

    @abstractmethod
    def create_transaction(
        self,
        options: Optional[TransactionOptions] = None
    ) -> BaseVectorTransaction:
        pass

    @abstractmethod
    def begin(self, options: Optional[TransactionOptions] = None) -> BaseVectorTransaction:
        pass
