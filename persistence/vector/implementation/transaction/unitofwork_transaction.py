import uuid
import logging
from typing import Optional, Any, Callable

from persistence.protocols.transaction.base import (
    BaseTransaction,
    BaseTransactionManager,
    TransactionState,
    TransactionOptions,
    TransactionResult
)
from persistence.vector.protocol.vector_transaction import (
    BaseVectorTransaction,
    BaseVectorTransactionManager,
    VectorStorageConnection
)
from persistence.vector.implementation.domain.VectorItem import VectorItem

logger = logging.getLogger(__name__)


class UnitOfWorkVectorTransaction(BaseVectorTransaction):
    """应用层 UnitOfWork 模式的事务实现"""
    
    def __init__(
        self,
        transaction_id: str,
        connection: VectorStorageConnection,
        options: Optional[TransactionOptions] = None
    ):
        self._transaction_id = transaction_id
        self._connection = connection
        self._options = options or TransactionOptions()
        self._state = TransactionState.INACTIVE
        self._savepoints: dict[str, dict] = {}
        self._added_items: list[VectorItem] = []
        self._updated_items: list[VectorItem] = []
        self._deleted_ids: list[str] = []
        
        logger.info(f"UnitOfWorkVectorTransaction created: {self._transaction_id}")
    
    @property
    def transaction_id(self) -> str:
        return self._transaction_id
    
    @property
    def state(self) -> TransactionState:
        return self._state
    
    @property
    def is_active(self) -> bool:
        return self._state == TransactionState.ACTIVE
    
    @property
    def storage_connection(self) -> VectorStorageConnection:
        return self._connection
    
    def begin(self, options: Optional[TransactionOptions] = None) -> None:
        if self._state != TransactionState.INACTIVE:
            raise RuntimeError(f"Cannot begin transaction in state: {self._state}")
        
        if options:
            self._options = options
        
        self._state = TransactionState.ACTIVE
        self._added_items = []
        self._updated_items = []
        self._deleted_ids = []
        self._savepoints = {}
        logger.info(f"UnitOfWorkVectorTransaction {self._transaction_id} started")
    
    def commit(self) -> TransactionResult:
        if not self.is_active:
            return TransactionResult(
                success=False,
                message=f"Cannot commit transaction in state: {self._state}"
            )
        
        try:
            if self._deleted_ids:
                self._connection.delete_vectors(self._deleted_ids)
                logger.debug(f"Deleted {len(self._deleted_ids)} vectors")
            
            if self._added_items:
                self._connection.add_vectors(self._added_items)
                logger.debug(f"Added {len(self._added_items)} vectors")
            
            if self._updated_items:
                self._connection.update_vectors(self._updated_items)
                logger.debug(f"Updated {len(self._updated_items)} vectors")
            
            self._state = TransactionState.COMMITTED
            self._clear_pending()
            logger.info(f"UnitOfWorkVectorTransaction {self._transaction_id} committed")
            
            return TransactionResult(success=True, message="Transaction committed")
            
        except Exception as e:
            self._state = TransactionState.FAILED
            self._clear_pending()
            logger.error(f"UnitOfWorkVectorTransaction {self._transaction_id} commit failed: {e}")
            return TransactionResult(success=False, message=str(e), error=e)
    
    def rollback(self, reason: Optional[str] = None) -> TransactionResult:
        if self._state not in [TransactionState.ACTIVE, TransactionState.FAILED]:
            return TransactionResult(
                success=False,
                message=f"Cannot rollback transaction in state: {self._state}"
            )
        
        self._clear_pending()
        self._state = TransactionState.ROLLED_BACK
        logger.info(f"UnitOfWorkVectorTransaction {self._transaction_id} rolled back: {reason}")
        
        return TransactionResult(
            success=True,
            message=f"Transaction rolled back: {reason or 'No reason provided'}"
        )
    
    def savepoint(self, name: str) -> None:
        if not self.is_active:
            raise RuntimeError("Cannot create savepoint outside active transaction")
        
        self._savepoints[name] = {
            'added': list(self._added_items),
            'updated': list(self._updated_items),
            'deleted': list(self._deleted_ids)
        }
        logger.debug(f"Savepoint '{name}' created for transaction {self._transaction_id}")
    
    def rollback_to_savepoint(self, name: str) -> None:
        if not self.is_active:
            raise RuntimeError("Cannot rollback savepoint outside active transaction")
        
        if name not in self._savepoints:
            raise ValueError(f"Savepoint '{name}' not found")
        
        state = self._savepoints[name]
        self._added_items = list(state['added'])
        self._updated_items = list(state['updated'])
        self._deleted_ids = list(state['deleted'])
        logger.debug(f"Rolled back to savepoint '{name}' in transaction {self._transaction_id}")
    
    def release_savepoint(self, name: str) -> None:
        if name in self._savepoints:
            del self._savepoints[name]
            logger.debug(f"Savepoint '{name}' released")
    
    def add_vectors(self, items: list[VectorItem]) -> bool:
        if not self.is_active:
            logger.warning("Cannot add vectors outside active transaction")
            return False
        
        self._added_items.extend(items)
        logger.debug(f"Added {len(items)} vectors to pending operations")
        return True
    
    def delete_vectors(self, ids: list[str]) -> bool:
        if not self.is_active:
            logger.warning("Cannot delete vectors outside active transaction")
            return False
        
        self._deleted_ids.extend(ids)
        logger.debug(f"Marked {len(ids)} vectors for deletion")
        return True
    
    def update_vectors(self, items: list[VectorItem]) -> bool:
        if not self.is_active:
            logger.warning("Cannot update vectors outside active transaction")
            return False
        
        self._updated_items.extend(items)
        logger.debug(f"Added {len(items)} vectors for update")
        return True
    
    def search(
        self,
        query_vector: list[float],
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> list[tuple[VectorItem, float]]:
        raise NotImplementedError("Search should be done through QueryEngine, not storage transaction")
    
    def _clear_pending(self) -> None:
        self._added_items = []
        self._updated_items = []
        self._deleted_ids = []


class UnitOfWorkVectorTransactionManager(BaseVectorTransactionManager):
    """基于 UnitOfWork 的向量数据库事务管理器"""
    
    def __init__(self, storage_connection: VectorStorageConnection):
        self._storage_connection = storage_connection
        self._current_transaction: Optional[UnitOfWorkVectorTransaction] = None
    
    @property
    def current_transaction(self) -> Optional[BaseTransaction]:
        return self._current_transaction
    
    @property
    def is_in_transaction(self) -> bool:
        return self._current_transaction is not None and self._current_transaction.is_active
    
    @property
    def storage_backend(self) -> str:
        return "unitofwork"
    
    @property
    def supports_native_transactions(self) -> bool:
        return False
    
    def create_transaction(
        self,
        options: Optional[TransactionOptions] = None
    ) -> BaseVectorTransaction:
        transaction_id = str(uuid.uuid4())
        return UnitOfWorkVectorTransaction(transaction_id, self._storage_connection, options)
    
    def begin(self, options: Optional[TransactionOptions] = None) -> BaseVectorTransaction:
        if self.is_in_transaction:
            raise RuntimeError("Transaction already in progress")
        
        self._current_transaction = self.create_transaction(options)
        self._current_transaction.begin(options)
        return self._current_transaction
    
    def commit(self) -> TransactionResult:
        if not self.is_in_transaction:
            return TransactionResult(success=False, message="No active transaction")
        
        result = self._current_transaction.commit()
        self._current_transaction = None
        return result
    
    def rollback(self, reason: Optional[str] = None) -> TransactionResult:
        if not self.is_in_transaction and self._current_transaction is not None:
            result = self._current_transaction.rollback(reason)
            self._current_transaction = None
            return result
        
        if not self.is_in_transaction:
            return TransactionResult(success=False, message="No active transaction")
        
        result = self._current_transaction.rollback(reason)
        self._current_transaction = None
        return result
    
    def execute_in_transaction(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> Any:
        if self.is_in_transaction:
            return func(*args, **kwargs)
        
        self.begin()
        try:
            result = func(*args, **kwargs)
            self.commit()
            return result
        except Exception as e:
            self.rollback(str(e))
            raise
    
    def with_transaction(
        self,
        options: Optional[TransactionOptions] = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return self.execute_in_transaction(func, *args, **kwargs)
            return wrapper
        return decorator