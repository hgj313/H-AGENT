"""Checkpoint Manager Module

Manages checkpoint creation, storage, and retrieval for workflow execution.
Following the architecture: State persistence for recovery

Features:
- Manual and automatic checkpoint creation
- Configurable triggers
- Checkpoint metadata tracking
- State compression
- Checkpoint TTL management
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
import threading
import uuid
import json
import copy


class CheckpointTrigger(Enum):
    """Checkpoint trigger types"""
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    ON_ERROR = "on_error"
    ON_NODE_COMPLETE = "on_node_complete"
    ON_CONDITION = "on_condition"
    TIMED = "timed"


@dataclass
class CheckpointMetadata:
    """Metadata for checkpoints"""
    checkpoint_id: str
    run_id: str
    thread_id: Optional[str] = None
    node_name: Optional[str] = None
    trigger: CheckpointTrigger = CheckpointTrigger.MANUAL
    created_at: datetime = field(default_factory=datetime.now)
    description: Optional[str] = None
    version: str = "1.0"
    parent_checkpoint_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Checkpoint:
    """Checkpoint data structure
    
    Represents a snapshot of workflow state for recovery.
    """
    id: str
    state: dict[str, Any]
    metadata: CheckpointMetadata
    state_snapshot: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert checkpoint to dictionary"""
        return {
            'id': self.id,
            'state': self.state,
            'metadata': {
                'checkpoint_id': self.metadata.checkpoint_id,
                'run_id': self.metadata.run_id,
                'thread_id': self.metadata.thread_id,
                'node_name': self.metadata.node_name,
                'trigger': self.metadata.trigger.value,
                'created_at': self.metadata.created_at.isoformat(),
                'description': self.metadata.description,
                'version': self.metadata.version,
                'parent_checkpoint_id': self.metadata.parent_checkpoint_id,
                'tags': self.metadata.tags,
                'metadata': self.metadata.metadata
            },
            'state_snapshot': self.state_snapshot
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Checkpoint':
        """Create checkpoint from dictionary"""
        metadata_dict = data['metadata']
        metadata = CheckpointMetadata(
            checkpoint_id=metadata_dict['checkpoint_id'],
            run_id=metadata_dict['run_id'],
            thread_id=metadata_dict.get('thread_id'),
            node_name=metadata_dict.get('node_name'),
            trigger=CheckpointTrigger(metadata_dict['trigger']),
            created_at=datetime.fromisoformat(metadata_dict['created_at']),
            description=metadata_dict.get('description'),
            version=metadata_dict.get('version', '1.0'),
            parent_checkpoint_id=metadata_dict.get('parent_checkpoint_id'),
            tags=metadata_dict.get('tags', []),
            metadata=metadata_dict.get('metadata', {})
        )
        return cls(
            id=data['id'],
            state=data['state'],
            metadata=metadata,
            state_snapshot=data.get('state_snapshot')
        )


@dataclass
class CheckpointConfig:
    """Configuration for checkpoint manager"""
    enabled: bool = True
    auto_trigger_nodes: list[str] = field(default_factory=list)
    trigger_on_error: bool = True
    max_checkpoints: int = 100
    checkpoint_ttl_seconds: Optional[int] = None
    storage_backend: Optional[str] = None
    compress_state: bool = False
    include_secrets: bool = False


class CheckpointManager:
    """Manages checkpoint creation and storage
    
    Following the architecture: 一级持久化 for crash recovery
    
    Usage:
        manager = CheckpointManager()
        checkpoint = manager.create_checkpoint(
            state=current_state,
            run_id="run_123",
            trigger=CheckpointTrigger.ON_NODE_COMPLETE,
            node_name="agent_node"
        )
        
        # Resume from checkpoint
        restored_state = manager.restore_checkpoint(checkpoint.id)
    """
    
    def __init__(
        self,
        config: Optional[CheckpointConfig] = None,
        storage: Optional['CheckpointStorage'] = None
    ):
        self.config = config or CheckpointConfig()
        self.storage = storage
        self._lock = threading.RLock()
        self._checkpoints: dict[str, list[Checkpoint]] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._condition_functions: dict[str, Callable] = {}
    
    def create_checkpoint(
        self,
        state: dict[str, Any],
        run_id: str,
        trigger: CheckpointTrigger = CheckpointTrigger.MANUAL,
        thread_id: Optional[str] = None,
        node_name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None
    ) -> Checkpoint:
        """Create a new checkpoint
        
        Args:
            state: Current workflow state
            run_id: Current run ID
            trigger: What triggered this checkpoint
            thread_id: Optional thread ID
            node_name: Optional node name
            description: Optional description
            tags: Optional tags
            metadata: Optional metadata
            
        Returns:
            Created Checkpoint
        """
        checkpoint_id = str(uuid.uuid4())
        
        state_copy = copy.deepcopy(state)
        if not self.config.include_secrets:
            state_copy = self._remove_secrets(state_copy)
        
        if self.config.compress_state:
            import gzip
            import base64
            state_json = json.dumps(state_copy, default=str)
            compressed = gzip.compress(state_json.encode())
            state_snapshot = base64.b64encode(compressed).decode()
        else:
            state_snapshot = None
        
        meta = CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            run_id=run_id,
            thread_id=thread_id,
            node_name=node_name,
            trigger=trigger,
            created_at=datetime.now(),
            description=description,
            tags=tags or [],
            metadata=metadata or {}
        )
        
        checkpoint = Checkpoint(
            id=checkpoint_id,
            state=state_copy,
            metadata=meta,
            state_snapshot=state_snapshot
        )
        
        with self._lock:
            key = f"{run_id}:{thread_id or 'default'}"
            if key not in self._checkpoints:
                self._checkpoints[key] = []
            
            self._checkpoints[key].append(checkpoint)
            
            if len(self._checkpoints[key]) > self.config.max_checkpoints:
                self._checkpoints[key].pop(0)
        
        if self.storage:
            self.storage.save(checkpoint)
        
        self._notify_callbacks(checkpoint)
        
        return checkpoint
    
    def get_checkpoint(
        self,
        checkpoint_id: str,
        run_id: Optional[str] = None,
        thread_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Get a checkpoint by ID
        
        Args:
            checkpoint_id: Checkpoint ID
            run_id: Optional run ID
            thread_id: Optional thread ID
            
        Returns:
            Checkpoint or None
        """
        if self.storage:
            return self.storage.load(checkpoint_id)
        
        with self._lock:
            for checkpoints in self._checkpoints.values():
                for cp in checkpoints:
                    if cp.id == checkpoint_id:
                        return cp
            return None
    
    def get_latest(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Get the latest checkpoint for a run
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            
        Returns:
            Latest Checkpoint or None
        """
        if self.storage:
            return self.storage.load_latest(run_id, thread_id)
        
        with self._lock:
            key = f"{run_id}:{thread_id or 'default'}"
            checkpoints = self._checkpoints.get(key, [])
            return checkpoints[-1] if checkpoints else None
    
    def restore_checkpoint(self, checkpoint_id: str) -> Optional[dict]:
        """Restore state from checkpoint
        
        Args:
            checkpoint_id: Checkpoint ID
            
        Returns:
            Restored state or None
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            return None
        
        return self._decompress_state(checkpoint.state, checkpoint.state_snapshot)
    
    def list_checkpoints(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> list[Checkpoint]:
        """List all checkpoints for a run
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            
        Returns:
            List of Checkpoints
        """
        if self.storage:
            return self.storage.list_checkpoints(run_id, thread_id)
        
        with self._lock:
            key = f"{run_id}:{thread_id or 'default'}"
            return self._checkpoints.get(key, [])
    
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint
        
        Args:
            checkpoint_id: Checkpoint ID
            
        Returns:
            True if deleted
        """
        if self.storage:
            return self.storage.delete(checkpoint_id)
        
        with self._lock:
            for key, checkpoints in self._checkpoints.items():
                for i, cp in enumerate(checkpoints):
                    if cp.id == checkpoint_id:
                        checkpoints.pop(i)
                        return True
            return False
    
    def register_callback(
        self,
        event: str,
        callback: Callable[[Checkpoint], None]
    ) -> None:
        """Register a callback for checkpoint events
        
        Args:
            event: Event name (created, deleted, etc.)
            callback: Callback function
        """
        with self._lock:
            if event not in self._callbacks:
                self._callbacks[event] = []
            self._callbacks[event].append(callback)
    
    def register_condition(
        self,
        name: str,
        condition_func: Callable[[dict], bool]
    ) -> None:
        """Register a condition for automatic checkpointing
        
        Args:
            name: Condition name
            condition_func: Function that returns True when checkpoint should be created
        """
        with self._lock:
            self._condition_functions[name] = condition_func
    
    def should_checkpoint(self, state: dict, node_name: str) -> bool:
        """Check if checkpoint should be created based on conditions
        
        Args:
            state: Current state
            node_name: Current node name
            
        Returns:
            True if should checkpoint
        """
        if not self.config.enabled:
            return False
        
        if node_name in self.config.auto_trigger_nodes:
            return True
        
        for condition_func in self._condition_functions.values():
            if condition_func(state):
                return True
        
        return False
    
    def _remove_secrets(self, state: dict) -> dict:
        """Remove secrets from state"""
        secret_keys = {'password', 'secret', 'api_key', 'token', 'credential'}
        
        def recursive_remove(obj):
            if isinstance(obj, dict):
                return {
                    k: recursive_remove(v) if k.lower() not in secret_keys else '[REDACTED]'
                    for k, v in obj.items()
                }
            elif isinstance(obj, list):
                return [recursive_remove(item) for item in obj]
            return obj
        
        return recursive_remove(state)
    
    def _decompress_state(
        self,
        state: dict,
        state_snapshot: Optional[str]
    ) -> dict:
        """Decompress state if needed"""
        if state_snapshot and self.config.compress_state:
            import gzip
            import base64
            compressed = base64.b64decode(state_snapshot)
            decompressed = gzip.decompress(compressed)
            return json.loads(decompressed.decode())
        return state
    
    def _notify_callbacks(self, checkpoint: Checkpoint) -> None:
        """Notify registered callbacks"""
        callbacks = self._callbacks.get('created', [])
        for callback in callbacks:
            try:
                callback(checkpoint)
            except Exception:
                pass


def create_checkpoint_manager(
    storage_type: str = "memory",
    **config
) -> CheckpointManager:
    """Factory function to create checkpoint manager
    
    Args:
        storage_type: Storage type (memory/file/sqlite)
        **config: Configuration options
        
    Returns:
        CheckpointManager instance
    """
    from .storage import FileCheckpointStorage, MemoryCheckpointStorage
    
    storage = None
    if storage_type == "file":
        base_path = config.get('base_path', './checkpoints')
        storage = FileCheckpointStorage(base_path=base_path)
    elif storage_type == "sqlite":
        db_path = config.get('db_path', './checkpoints.db')
        storage = SQLiteCheckpointStorage(db_path=db_path)
    elif storage_type == "memory":
        storage = MemoryCheckpointStorage()
    
    checkpoint_config = CheckpointConfig(**config)
    
    return CheckpointManager(config=checkpoint_config, storage=storage)