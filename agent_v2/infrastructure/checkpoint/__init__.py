"""Checkpoint Infrastructure Module

Provides checkpoint functionality for workflow state persistence.
Following the architecture: 一级持久化 for crash recovery

Components:
- manager: Checkpoint creation and management
- storage: Storage backends (memory/file/sqlite)
- trigger: Configurable trigger policies
"""

from .manager import (
    CheckpointTrigger,
    CheckpointMetadata,
    Checkpoint,
    CheckpointConfig,
    CheckpointManager,
    create_checkpoint_manager,
)

from .storage import (
    CheckpointStorage,
    MemoryCheckpointStorage,
    FileCheckpointStorage,
    SQLiteCheckpointStorage,
)

from .trigger import (
    TriggerFrequency,
    TriggerCondition,
    CheckpointTriggerPolicy,
    ConditionalCheckpointPolicy,
)


__all__ = [
    # Manager
    "CheckpointTrigger",
    "CheckpointMetadata",
    "Checkpoint",
    "CheckpointConfig",
    "CheckpointManager",
    "create_checkpoint_manager",
    # Storage
    "CheckpointStorage",
    "MemoryCheckpointStorage",
    "FileCheckpointStorage",
    "SQLiteCheckpointStorage",
    # Trigger
    "TriggerFrequency",
    "TriggerCondition",
    "CheckpointTriggerPolicy",
    "ConditionalCheckpointPolicy",
]