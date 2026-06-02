"""Checkpoint Manager Module

Manages checkpoint creation, storage, and retrieval for workflow execution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
import threading
import uuid

import json


class CheckpointTrigger(Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    ON_ERROR = "on_error"
    ON_NODE_COMPLETE = "on_node_complete"
    ON_CONDITION = "on_condition"
    TIMED = "timed"


@dataclass
class CheckpointMetadata:
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
    id: str
    state: dict[str, Any]
    metadata: CheckpointMetadata
    state_snapshot: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert checkpoint to dictionary."""
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
        """Create checkpoint from dictionary."""
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
    enabled: bool = True
    auto_trigger_nodes: list[str] = field(default_factory=list)
    trigger_on_error: bool = True
    max_checkpoints: int = 100
    checkpoint_ttl_seconds: Optional[int] = None
    storage_backend: Optional[str] = None
    compress_state: bool = False
    include_secrets: bool = False


class CheckpointManager:
    """Manages checkpoint creation and storage for workflow execution.
    
    Features:
    - Manual and automatic checkpoint creation
    - Configurable triggers
    - Checkpoint metadata tracking
    - State compression
    - Checkpoint TTL management
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
        """Create a new checkpoint.
        
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
        
        import copy
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
        
        self._trigger_callbacks(checkpoint)
        
        return checkpoint
    
    def _remove_secrets(self, data: Any) -> Any:
        """Remove secret values from state."""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if any(s in key.lower() for s in ['password', 'secret', 'token', 'key', 'api']):
                    result[key] = '[REDACTED]'
                else:
                    result[key] = self._remove_secrets(value)
            return result
        elif isinstance(data, list):
            return [self._remove_secrets(item) for item in data]
        return data
    
    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Get a checkpoint by ID.
        
        Args:
            checkpoint_id: Checkpoint ID
            
        Returns:
            Checkpoint or None
        """
        with self._lock:
            for checkpoints in self._checkpoints.values():
                for cp in checkpoints:
                    if cp.id == checkpoint_id:
                        return cp
        
        if self.storage:
            return self.storage.load(checkpoint_id)
        
        return None
    
    def get_latest_checkpoint(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Get the latest checkpoint for a run.
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            
        Returns:
            Latest Checkpoint or None
        """
        with self._lock:
            key = f"{run_id}:{thread_id or 'default'}"
            checkpoints = self._checkpoints.get(key, [])
            if checkpoints:
                return checkpoints[-1]
        
        if self.storage:
            return self.storage.load_latest(run_id, thread_id)
        
        return None
    
    def list_checkpoints(
        self,
        run_id: str,
        thread_id: Optional[str] = None,
        tags: Optional[list[str]] = None
    ) -> list[Checkpoint]:
        """List checkpoints for a run.
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            tags: Optional filter by tags
            
        Returns:
            List of Checkpoints
        """
        with self._lock:
            key = f"{run_id}:{thread_id or 'default'}"
            checkpoints = self._checkpoints.get(key, [])
            
            if tags:
                checkpoints = [
                    cp for cp in checkpoints
                    if any(tag in cp.metadata.tags for tag in tags)
                ]
            
            return checkpoints
        
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint.
        
        Args:
            checkpoint_id: Checkpoint ID
            
        Returns:
            True if deleted
        """
        with self._lock:
            for key, checkpoints in self._checkpoints.items():
                for i, cp in enumerate(checkpoints):
                    if cp.id == checkpoint_id:
                        del checkpoints[i]
                        if self.storage:
                            self.storage.delete(checkpoint_id)
                        return True
        return False
    
    def register_callback(
        self,
        trigger: CheckpointTrigger,
        callback: Callable[[Checkpoint], None]
    ) -> None:
        """Register a callback for checkpoint events.
        
        Args:
            trigger: Checkpoint trigger type
            callback: Callback function
        """
        with self._lock:
            if trigger.value not in self._callbacks:
                self._callbacks[trigger.value] = []
            self._callbacks[trigger.value].append(callback)
    
    def _trigger_callbacks(self, checkpoint: Checkpoint) -> None:
        """Trigger registered callbacks."""
        callbacks = self._callbacks.get(checkpoint.metadata.trigger.value, [])
        for callback in callbacks:
            try:
                callback(checkpoint)
            except Exception:
                pass
    
    def register_condition(
        self,
        name: str,
        condition_func: Callable[[dict[str, Any]], bool]
    ) -> None:
        """Register a condition function for conditional checkpointing.
        
        Args:
            name: Condition name
            condition_func: Function that returns True when checkpoint should be created
        """
        with self._lock:
            self._condition_functions[name] = condition_func
    
    def check_conditions(self, state: dict[str, Any]) -> list[str]:
        """Check all registered conditions against current state.
        
        Args:
            state: Current state
            
        Returns:
            List of condition names that returned True
        """
        triggered = []
        for name, func in self._condition_functions.items():
            try:
                if func(state):
                    triggered.append(name)
            except Exception:
                pass
        return triggered
    
    def should_checkpoint(
        self,
        node_name: str,
        state: dict[str, Any],
        error: Optional[Exception] = None
    ) -> bool:
        """Determine if a checkpoint should be created.
        
        Args:
            node_name: Current node name
            state: Current state
            error: Optional error that occurred
            
        Returns:
            True if checkpoint should be created
        """
        if not self.config.enabled:
            return False
        
        if node_name in self.config.auto_trigger_nodes:
            return True
        
        if error and self.config.trigger_on_error:
            return True
        
        triggered_conditions = self.check_conditions(state)
        if triggered_conditions:
            return True
        
        return False
    
    def cleanup_old_checkpoints(
        self,
        run_id: str,
        thread_id: Optional[str] = None,
        keep_count: int = 5
    ) -> int:
        """Clean up old checkpoints, keeping only the most recent ones.
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            keep_count: Number of checkpoints to keep
            
        Returns:
            Number of checkpoints deleted
        """
        with self._lock:
            key = f"{run_id}:{thread_id or 'default'}"
            checkpoints = self._checkpoints.get(key, [])
            
            if len(checkpoints) <= keep_count:
                return 0
            
            deleted = 0
            to_delete = checkpoints[:-keep_count]
            
            for cp in to_delete:
                if self.storage:
                    self.storage.delete(cp.id)
                deleted += 1
            
            self._checkpoints[key] = checkpoints[-keep_count:]
            return deleted


class CheckpointManagerSingleton:
    """Singleton wrapper for CheckpointManager."""
    
    _instance: Optional[CheckpointManager] = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(
        cls,
        config: Optional[CheckpointConfig] = None,
        storage: Optional['CheckpointStorage'] = None
    ) -> CheckpointManager:
        """Get or create the singleton instance.
        
        Args:
            config: Optional configuration
            storage: Optional storage backend
            
        Returns:
            CheckpointManager instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = CheckpointManager(config, storage)
            return cls._instance
    
    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance."""
        with cls._lock:
            cls._instance = None


def get_checkpoint_manager(
    config: Optional[CheckpointConfig] = None,
    storage: Optional['CheckpointStorage'] = None
) -> CheckpointManager:
    """Convenience function to get the checkpoint manager.
    
    Args:
        config: Optional configuration
        storage: Optional storage backend
        
    Returns:
        CheckpointManager instance
    """
    return CheckpointManagerSingleton.get_instance(config, storage)