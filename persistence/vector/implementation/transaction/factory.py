"""
事务管理器工厂 - 为不同存储类型创建对应的事务管理器
"""
from persistence.vector.protocol.storage import BaseVectorStorage
from persistence.protocols.transaction import BaseTransactionManager


class TransactionManagerFactory:
    """事务管理器工厂"""
    
    @staticmethod
    def create_for_chroma(storage: BaseVectorStorage) -> BaseTransactionManager:
        from persistence.vector.implementation.transaction.chroma_transaction import (
            ChromaVectorStorageConnection,
            ChromaVectorTransactionManager
        )
        
        connection = ChromaVectorStorageConnection(storage)
        connection.connect()
        
        return ChromaVectorTransactionManager(connection)
    
    @staticmethod
    def create(
        storage: BaseVectorStorage,
        backend_type: str = "chroma"
    ) -> BaseTransactionManager:
        """根据后端类型创建事务管理器"""
        if backend_type.lower() == "chroma":
            return TransactionManagerFactory.create_for_chroma(storage)
        raise ValueError(f"Unsupported backend type: {backend_type}")