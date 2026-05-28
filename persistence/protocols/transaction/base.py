from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime


class TransactionState(Enum):
    """事务状态枚举"""
    INACTIVE = "inactive"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class IsolationLevel(Enum):
    """隔离级别枚举"""
    READ_UNCOMMITTED = "read_uncommitted"
    READ_COMMITTED = "read_committed"
    REPEATABLE_READ = "repeatable_read"
    SERIALIZABLE = "serializable"
    SNAPSHOT = "snapshot"


@dataclass
class TransactionOptions:
    """事务配置选项"""
    isolation_level: IsolationLevel = IsolationLevel.READ_COMMITTED
    timeout: Optional[int] = None
    read_only: bool = False
    max_retries: int = 3
    retry_delay: float = 0.1


@dataclass
class TransactionResult:
    """事务执行结果"""
    success: bool
    message: str = ""
    error: Optional[Exception] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class BaseTransaction(ABC):
    """事务核心抽象协议 - 所有事务类型的基类"""
    
    @property
    @abstractmethod
    def transaction_id(self) -> str:
        """获取事务唯一标识"""
        pass
    
    @property
    @abstractmethod
    def state(self) -> TransactionState:
        """获取当前事务状态"""
        pass
    
    @property
    @abstractmethod
    def is_active(self) -> bool:
        """判断事务是否处于活跃状态"""
        pass
    
    @abstractmethod
    def begin(self, options: Optional[TransactionOptions] = None) -> None:
        """开始事务"""
        pass
    
    @abstractmethod
    def commit(self) -> TransactionResult:
        """提交事务"""
        pass
    
    @abstractmethod
    def rollback(self, reason: Optional[str] = None) -> TransactionResult:
        """回滚事务"""
        pass
    
    @abstractmethod
    def savepoint(self, name: str) -> None:
        """创建保存点"""
        pass
    
    @abstractmethod
    def rollback_to_savepoint(self, name: str) -> None:
        """回滚到指定保存点"""
        pass
    
    @abstractmethod
    def release_savepoint(self, name: str) -> None:
        """释放保存点"""
        pass


class BaseTransactionManager(ABC):
    """事务管理器抽象协议 - 管理事务的生命周期"""
    
    @property
    @abstractmethod
    def current_transaction(self) -> Optional[BaseTransaction]:
        """获取当前事务实例"""
        pass
    
    @property
    @abstractmethod
    def is_in_transaction(self) -> bool:
        """判断是否处于事务中"""
        pass
    
    @abstractmethod
    def begin(self, options: Optional[TransactionOptions] = None) -> BaseTransaction:
        """开始新事务"""
        pass
    
    @abstractmethod
    def commit(self) -> TransactionResult:
        """提交当前事务"""
        pass
    
    @abstractmethod
    def rollback(self, reason: Optional[str] = None) -> TransactionResult:
        """回滚当前事务"""
        pass
    
    @abstractmethod
    def execute_in_transaction(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """在事务中执行函数"""
        pass
    
    @abstractmethod
    def with_transaction(
        self,
        options: Optional[TransactionOptions] = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """事务装饰器"""
        pass