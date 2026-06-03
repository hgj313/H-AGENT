"""Infrastructure Module

Provides infrastructure components for the agent system.
Following the architecture: Infrastructure = 基础设施

Components:
- checkpoint: Checkpoint management for state persistence
- persistence: Persistence manager with multiple backends
- interrupt: Interrupt controller for human-in-the-loop
- middleware: Middleware for interception and modification
- llm: LLM factory and configuration
"""

from .checkpoint import (
    CheckpointTrigger,
    CheckpointMetadata,
    Checkpoint,
    CheckpointConfig,
    CheckpointManager,
    CheckpointStorage,
    MemoryCheckpointStorage,
    FileCheckpointStorage,
    SQLiteCheckpointStorage,
    CheckpointTriggerPolicy,
    ConditionalCheckpointPolicy,
    create_checkpoint_manager,
)

from .persistence import (
    PersistenceBackend,
    StateRecord,
    WorkflowSnapshot,
    PersistenceConfig,
    PersistenceManager,
    PersistenceBackendBase,
    MemoryPersistenceBackend,
    FilePersistenceBackend,
    SQLitePersistenceBackend,
    BackupManager,
    BackupStrategy,
    BackupMetadata,
    create_persistence_manager,
    create_backup_manager,
)

from .interrupt import (
    InterruptReason,
    InterruptRequest,
    InterruptResult,
    NodeBreakpoint,
    WorkflowState,
    InterruptController,
    ResumptionConfig,
    ResumptionResult,
    WorkflowResumer,
    create_interrupt_controller,
    create_workflow_resumer,
)

from .middleware import (
    MiddlewareOrder,
    MiddlewareContext,
    MiddlewareResult,
    MiddlewareChain,
    Middleware,
    LoggingMiddleware,
    TimingMiddleware,
    ErrorHandlerMiddleware,
    MiddlewareManager,
    MiddlewareConfig,
    IntegrationMode,
    RequestData,
    ResponseData,
    InterceptorMiddleware,
    RateLimitMiddleware,
    create_middleware_manager,
)

from .llm import (
    LLMProvider,
    LLMConfig,
    LLMFactory,
    get_llm_factory,
    create_llm,
)


__all__ = [
    # Checkpoint
    "CheckpointTrigger",
    "CheckpointMetadata",
    "Checkpoint",
    "CheckpointConfig",
    "CheckpointManager",
    "CheckpointStorage",
    "MemoryCheckpointStorage",
    "FileCheckpointStorage",
    "SQLiteCheckpointStorage",
    "CheckpointTriggerPolicy",
    "ConditionalCheckpointPolicy",
    "create_checkpoint_manager",
    # Persistence
    "PersistenceBackend",
    "StateRecord",
    "WorkflowSnapshot",
    "PersistenceConfig",
    "PersistenceManager",
    "PersistenceBackendBase",
    "MemoryPersistenceBackend",
    "FilePersistenceBackend",
    "SQLitePersistenceBackend",
    "BackupManager",
    "BackupStrategy",
    "BackupMetadata",
    "create_persistence_manager",
    "create_backup_manager",
    # Interrupt
    "InterruptReason",
    "InterruptRequest",
    "InterruptResult",
    "NodeBreakpoint",
    "WorkflowState",
    "InterruptController",
    "ResumptionConfig",
    "ResumptionResult",
    "WorkflowResumer",
    "create_interrupt_controller",
    "create_workflow_resumer",
    # Middleware
    "MiddlewareOrder",
    "MiddlewareContext",
    "MiddlewareResult",
    "MiddlewareChain",
    "Middleware",
    "LoggingMiddleware",
    "TimingMiddleware",
    "ErrorHandlerMiddleware",
    "MiddlewareManager",
    "MiddlewareConfig",
    "IntegrationMode",
    "RequestData",
    "ResponseData",
    "InterceptorMiddleware",
    "RateLimitMiddleware",
    "create_middleware_manager",
    # LLM
    "LLMProvider",
    "LLMConfig",
    "LLMFactory",
    "get_llm_factory",
    "create_llm",
]