from abc import ABC, abstractmethod
from typing import Optional, Any, Protocol, runtime_checkable
from enum import Enum

from persistence.protocols.transaction.base import (
    BaseTransaction,
    BaseTransactionManager,
    TransactionOptions,
    TransactionResult,
    IsolationLevel
)


class SQLDialect(Enum):
    """SQL方言枚举"""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLITE = "sqlite"
    ORACLE = "oracle"
    SQLSERVER = "sqlserver"


class RelationalConnection(Protocol):
    """关系型数据库连接接口"""
    
    @property
    def is_connected(self) -> bool:
        """检查连接状态"""
        ...
    
    @property
    def dialect(self) -> SQLDialect:
        """获取SQL方言"""
        ...
    
    @abstractmethod
    def connect(self) -> bool:
        """建立连接"""
        ...
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        ...
    
    @abstractmethod
    def execute(self, sql: str, params: Optional[tuple] = None) -> Any:
        """执行SQL"""
        ...
    
    @abstractmethod
    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """批量执行SQL"""
        ...
    
    @abstractmethod
    def fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[Any]:
        """查询单条"""
        ...
    
    @abstractmethod
    def fetch_all(self, sql: str, params: Optional[tuple] = None) -> list[Any]:
        """查询多条"""
        ...


class BaseRelationalTransaction(BaseTransaction):
    """关系型数据库事务抽象协议"""
    
    @property
    @abstractmethod
    def connection(self) -> RelationalConnection:
        """获取关联的数据库连接"""
        pass
    
    @property
    @abstractmethod
    def dialect(self) -> SQLDialect:
        """获取SQL方言"""
        pass
    
    @abstractmethod
    def execute(self, sql: str, params: Optional[tuple] = None) -> Any:
        """执行SQL语句"""
        pass
    
    @abstractmethod
    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """批量执行SQL语句"""
        pass
    
    @abstractmethod
    def fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[Any]:
        """查询单条记录"""
        pass
    
    @abstractmethod
    def fetch_all(self, sql: str, params: Optional[tuple] = None) -> list[Any]:
        """查询多条记录"""
        pass
    
    @abstractmethod
    def begin_savepoint(self, name: str) -> None:
        """创建SQL保存点（特定于关系型数据库）"""
        pass
    
    @abstractmethod
    def rollback_to_savepoint(self, name: str) -> None:
        """回滚到SQL保存点"""
        pass


class BaseRelationalTransactionManager(BaseTransactionManager):
    """关系型数据库事务管理器抽象协议"""
    
    @property
    @abstractmethod
    def dialect(self) -> SQLDialect:
        """获取SQL方言"""
        pass
    
    @property
    @abstractmethod
    def connection_pool_size(self) -> int:
        """获取连接池大小"""
        pass
    
    @abstractmethod
    def create_transaction(
        self,
        options: Optional[TransactionOptions] = None
    ) -> BaseRelationalTransaction:
        """创建新事务实例"""
        pass
    
    @abstractmethod
    def begin(self, options: Optional[TransactionOptions] = None) -> BaseRelationalTransaction:
        """开始新事务"""
        pass
    
    @abstractmethod
    def get_connection(self) -> RelationalConnection:
        """获取数据库连接"""
        pass
    
    @abstractmethod
    def release_connection(self, connection: RelationalConnection) -> None:
        """释放数据库连接回连接池"""
        pass