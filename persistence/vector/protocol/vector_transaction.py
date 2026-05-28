from abc import ABC, abstractmethod
from typing import Optional, Any, Callable, Protocol, runtime_checkable

from persistence.vector.implementation.domain.engine import EngineVectorItem
from persistence.protocols.transaction.base import (
    BaseTransaction,
    BaseTransactionManager,
    TransactionOptions,
    TransactionResult,
    IsolationLevel
)


@runtime_checkable
class VectorStorageConnection(Protocol):
    """向量数据库连接接口"""
    
    @property
    def is_connected(self) -> bool:
        """检查连接状态"""
        ...
    
    @abstractmethod
    def connect(self) -> bool:
        """建立连接"""
        ...
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        ...


class BaseVectorTransaction(BaseTransaction):
    """向量数据库事务抽象协议"""
    
    @property
    @abstractmethod
    def storage_connection(self) -> VectorStorageConnection:
        """获取关联的存储连接"""
        pass
    
    @abstractmethod
    def add_vectors(self, items: list[EngineVectorItem]) -> bool:
        """添加向量"""
        pass
    
    @abstractmethod
    def delete_vectors(self, ids: list[str]) -> bool:
        """删除向量"""
        pass
    
    @abstractmethod
    def update_vectors(self, items: list[EngineVectorItem]) -> bool:
        """更新向量"""
        pass
    
    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[tuple[EngineVectorItem, float]]:
        """搜索向量"""
        pass


class BaseVectorTransactionManager(BaseTransactionManager):
    """向量数据库事务管理器抽象协议"""
    
    @property
    @abstractmethod
    def storage_backend(self) -> str:
        """获取存储后端类型标识"""
        pass
    
    @property
    @abstractmethod
    def supports_native_transactions(self) -> bool:
        """判断底层存储是否原生支持事务"""
        pass
    
    @abstractmethod
    def create_transaction(
        self,
        options: Optional[TransactionOptions] = None
    ) -> BaseVectorTransaction:
        """创建新事务实例"""
        pass
    
    @abstractmethod
    def begin(self, options: Optional[TransactionOptions] = None) -> BaseVectorTransaction:
        """开始新事务（重写基类方法，返回具体类型）"""
        pass