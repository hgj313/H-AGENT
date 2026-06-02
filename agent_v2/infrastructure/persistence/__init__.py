"""Persistence Infrastructure Module

Provides persistence functionality for workflow state management.
Following the architecture: 状态持久化 with backup support

Components:
- persistence_manager: Main persistence manager with multiple backends
- backup: Backup and recovery functionality
"""

from .persistence_manager import (
    PersistenceBackend,
    StateRecord,
    WorkflowSnapshot,
    PersistenceConfig,
    PersistenceBackendBase,
    MemoryPersistenceBackend,
    FilePersistenceBackend,
    SQLitePersistenceBackend,
    PersistenceManager,
    create_persistence_manager,
)

from .backup import (
    BackupStrategy,
    BackupMetadata,
    BackupBackend,
    FileBackupBackend,
    BackupManager,
    create_backup_manager,
)


__all__ = [
    # Persistence Manager
    "PersistenceBackend",
    "StateRecord",
    "WorkflowSnapshot",
    "PersistenceConfig",
    "PersistenceBackendBase",
    "MemoryPersistenceBackend",
    "FilePersistenceBackend",
    "SQLitePersistenceBackend",
    "PersistenceManager",
    "create_persistence_manager",
    # Backup
    "BackupStrategy",
    "BackupMetadata",
    "BackupBackend",
    "FileBackupBackend",
    "BackupManager",
    "create_backup_manager",
]