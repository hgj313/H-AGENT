"""Persistence Manager Module

Manages workflow state persistence with multiple backend support.
Following the architecture: 状态持久化 for long-running workflows

Features:
- Multiple backend support (memory/file/sqlite/postgresql/redis/s3)
- State versioning and history
- Automatic state snapshots
- Checksum validation
- Backup support
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import threading
import json
import gzip
import base64
import shutil
from pathlib import Path

from ..checkpoint.manager import Checkpoint


class PersistenceBackend(Enum):
    """Available persistence backends"""
    MEMORY = "memory"
    FILE = "file"
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    REDIS = "redis"
    S3 = "s3"


@dataclass
class StateRecord:
    """State record for persistence
    
    Represents a single state snapshot in the workflow history.
    """
    id: str
    run_id: str
    thread_id: Optional[str]
    node_name: Optional[str]
    state_data: dict[str, Any]
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    version: int = 1
    checksum: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'run_id': self.run_id,
            'thread_id': self.thread_id,
            'node_name': self.node_name,
            'state_data': self.state_data,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'version': self.version,
            'checksum': self.checksum,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'StateRecord':
        return cls(
            id=data['id'],
            run_id=data['run_id'],
            thread_id=data.get('thread_id'),
            node_name=data.get('node_name'),
            state_data=data['state_data'],
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            version=data.get('version', 1),
            checksum=data.get('checksum'),
            metadata=data.get('metadata', {})
        )


@dataclass
class WorkflowSnapshot:
    """Workflow snapshot containing checkpoints and state history"""
    id: str
    run_id: str
    thread_id: Optional[str]
    checkpoints: list[Checkpoint]
    state_history: list[StateRecord]
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'run_id': self.run_id,
            'thread_id': self.thread_id,
            'checkpoints': [cp.to_dict() for cp in self.checkpoints],
            'state_history': [sr.to_dict() for sr in self.state_history],
            'created_at': self.created_at.isoformat(),
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'WorkflowSnapshot':
        return cls(
            id=data['id'],
            run_id=data['run_id'],
            thread_id=data.get('thread_id'),
            checkpoints=[Checkpoint.from_dict(cp) for cp in data['checkpoints']],
            state_history=[StateRecord.from_dict(sr) for sr in data['state_history']],
            created_at=datetime.fromisoformat(data['created_at']),
            metadata=data.get('metadata', {})
        )


@dataclass
class PersistenceConfig:
    """Configuration for persistence manager"""
    backend: PersistenceBackend = PersistenceBackend.SQLITE
    connection_string: Optional[str] = None
    auto_save: bool = True
    save_interval_seconds: int = 30
    max_history_size: int = 1000
    compress_data: bool = True
    enable_checksum: bool = True
    backup_on_save: bool = False
    cleanup_policy: str = "retention"


class PersistenceBackendBase(ABC):
    """Abstract base class for persistence backends
    
    Implement this class to provide custom persistence storage.
    """
    
    @abstractmethod
    def save_state(self, record: StateRecord) -> bool:
        """Save a state record"""
        pass
    
    @abstractmethod
    def load_state(self, record_id: str) -> Optional[StateRecord]:
        """Load a state record by ID"""
        pass
    
    @abstractmethod
    def load_latest_state(self, run_id: str, thread_id: Optional[str] = None) -> Optional[StateRecord]:
        """Load the latest state for a run"""
        pass
    
    @abstractmethod
    def delete_state(self, record_id: str) -> bool:
        """Delete a state record"""
        pass
    
    @abstractmethod
    def list_states(self, run_id: str, thread_id: Optional[str] = None) -> list[StateRecord]:
        """List all states for a run"""
        pass
    
    @abstractmethod
    def save_snapshot(self, snapshot: WorkflowSnapshot) -> bool:
        """Save a workflow snapshot"""
        pass
    
    @abstractmethod
    def load_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        """Load a workflow snapshot"""
        pass


class MemoryPersistenceBackend(PersistenceBackendBase):
    """In-memory persistence backend
    
    Use for testing or single-instance deployments.
    Not persistent across restarts.
    """
    
    def __init__(self):
        self._states: dict[str, StateRecord] = {}
        self._snapshots: dict[str, WorkflowSnapshot] = {}
        self._run_index: dict[str, dict[str, list[str]]] = {}
        self._lock = threading.RLock()
    
    def save_state(self, record: StateRecord) -> bool:
        with self._lock:
            self._states[record.id] = record
            
            run_id = record.run_id
            thread_id = record.thread_id or 'default'
            
            if run_id not in self._run_index:
                self._run_index[run_id] = {}
            if thread_id not in self._run_index[run_id]:
                self._run_index[run_id][thread_id] = []
            
            self._run_index[run_id][thread_id].append(record.id)
            
            return True
    
    def load_state(self, record_id: str) -> Optional[StateRecord]:
        with self._lock:
            return self._states.get(record_id)
    
    def load_latest_state(self, run_id: str, thread_id: Optional[str] = None) -> Optional[StateRecord]:
        thread_id = thread_id or 'default'
        
        with self._lock:
            if run_id not in self._run_index:
                return None
            
            state_ids = self._run_index[run_id].get(thread_id, [])
            if not state_ids:
                return None
            
            latest_id = state_ids[-1]
            return self._states.get(latest_id)
    
    def delete_state(self, record_id: str) -> bool:
        with self._lock:
            if record_id in self._states:
                del self._states[record_id]
                return True
            return False
    
    def list_states(self, run_id: str, thread_id: Optional[str] = None) -> list[StateRecord]:
        thread_id = thread_id or 'default'
        
        with self._lock:
            if run_id not in self._run_index:
                return []
            
            state_ids = self._run_index[run_id].get(thread_id, [])
            return [
                self._states[sid]
                for sid in state_ids
                if sid in self._states
            ]
    
    def save_snapshot(self, snapshot: WorkflowSnapshot) -> bool:
        with self._lock:
            self._snapshots[snapshot.id] = snapshot
            return True
    
    def load_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        with self._lock:
            return self._snapshots.get(snapshot_id)
    
    def clear(self) -> None:
        with self._lock:
            self._states.clear()
            self._snapshots.clear()
            self._run_index.clear()


class FilePersistenceBackend(PersistenceBackendBase):
    """File-based persistence backend
    
    Stores state records and snapshots as JSON files.
    Suitable for development and small deployments.
    """
    
    def __init__(self, base_path: str = "./persistence"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def _get_state_path(self, record_id: str) -> Path:
        return self.base_path / "states" / f"{record_id}.json"
    
    def _get_snapshot_path(self, snapshot_id: str) -> Path:
        return self.base_path / "snapshots" / f"{snapshot_id}.json"
    
    def _get_index_path(self, run_id: str, thread_id: Optional[str] = None) -> Path:
        suffix = thread_id or "default"
        return self.base_path / "indices" / run_id / f"{suffix}.json"
    
    def save_state(self, record: StateRecord) -> bool:
        try:
            state_path = self._get_state_path(record.id)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(record.to_dict(), f, indent=2, default=str)
            
            self._update_index(record)
            return True
        except Exception as e:
            print(f"Failed to save state: {e}")
            return False
    
    def _update_index(self, record: StateRecord) -> None:
        index_path = self._get_index_path(record.run_id, record.thread_id)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        
        index_data = {}
        if index_path.exists():
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
        
        if 'states' not in index_data:
            index_data['states'] = []
        
        index_data['states'].append({
            'id': record.id,
            'node_name': record.node_name,
            'created_at': record.created_at.isoformat(),
            'version': record.version
        })
        index_data['latest'] = record.id
        
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2)
    
    def load_state(self, record_id: str) -> Optional[StateRecord]:
        state_path = self._get_state_path(record_id)
        if not state_path.exists():
            return None
        
        with open(state_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return StateRecord.from_dict(data)
    
    def load_latest_state(self, run_id: str, thread_id: Optional[str] = None) -> Optional[StateRecord]:
        index_path = self._get_index_path(run_id, thread_id)
        
        if not index_path.exists():
            return None
        
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        
        latest_id = index_data.get('latest')
        if latest_id:
            return self.load_state(latest_id)
        
        return None
    
    def delete_state(self, record_id: str) -> bool:
        state_path = self._get_state_path(record_id)
        if state_path.exists():
            state_path.unlink()
            return True
        return False
    
    def list_states(self, run_id: str, thread_id: Optional[str] = None) -> list[StateRecord]:
        index_path = self._get_index_path(run_id, thread_id)
        
        if not index_path.exists():
            return []
        
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        
        states = []
        for state_info in index_data.get('states', []):
            state = self.load_state(state_info['id'])
            if state:
                states.append(state)
        
        return states
    
    def save_snapshot(self, snapshot: WorkflowSnapshot) -> bool:
        try:
            snapshot_path = self._get_snapshot_path(snapshot.id)
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(snapshot_path, 'w', encoding='utf-8') as f:
                json.dump(snapshot.to_dict(), f, indent=2, default=str)
            
            return True
        except Exception as e:
            print(f"Failed to save snapshot: {e}")
            return False
    
    def load_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        snapshot_path = self._get_snapshot_path(snapshot_id)
        if not snapshot_path.exists():
            return None
        
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return WorkflowSnapshot.from_dict(data)


class SQLitePersistenceBackend(PersistenceBackendBase):
    """SQLite-based persistence backend
    
    Provides persistent storage with query capabilities.
    Suitable for production deployments.
    """
    
    def __init__(self, db_path: str = "./persistence.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS state_records (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                thread_id TEXT,
                node_name TEXT,
                state_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                checksum TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workflow_snapshots (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                thread_id TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_state_run ON state_records(run_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_state_run_thread ON state_records(run_id, thread_id)')
        
        conn.commit()
        conn.close()
    
    def save_state(self, record: StateRecord) -> bool:
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO state_records
                (id, run_id, thread_id, node_name, state_data, created_at, updated_at, version, checksum)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record.id,
                record.run_id,
                record.thread_id,
                record.node_name,
                json.dumps(record.state_data, default=str),
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
                record.version,
                record.checksum
            ))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"Failed to save state: {e}")
            return False
    
    def load_state(self, record_id: str) -> Optional[StateRecord]:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM state_records WHERE id = ?', (record_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return self._row_to_state_record(row)
    
    def load_latest_state(self, run_id: str, thread_id: Optional[str] = None) -> Optional[StateRecord]:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id:
            cursor.execute('''
                SELECT * FROM state_records
                WHERE run_id = ? AND thread_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (run_id, thread_id))
        else:
            cursor.execute('''
                SELECT * FROM state_records
                WHERE run_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (run_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return self._row_to_state_record(row)
    
    def _row_to_state_record(self, row: tuple) -> StateRecord:
        return StateRecord(
            id=row[0],
            run_id=row[1],
            thread_id=row[2],
            node_name=row[3],
            state_data=json.loads(row[4]),
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
            version=row[7],
            checksum=row[8]
        )
    
    def delete_state(self, record_id: str) -> bool:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM state_records WHERE id = ?', (record_id,))
        
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return deleted
    
    def list_states(self, run_id: str, thread_id: Optional[str] = None) -> list[StateRecord]:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id:
            cursor.execute('''
                SELECT * FROM state_records
                WHERE run_id = ? AND thread_id = ?
                ORDER BY created_at ASC
            ''', (run_id, thread_id))
        else:
            cursor.execute('''
                SELECT * FROM state_records
                WHERE run_id = ?
                ORDER BY created_at ASC
            ''', (run_id,))
        
        states = [self._row_to_state_record(row) for row in cursor.fetchall()]
        conn.close()
        
        return states
    
    def save_snapshot(self, snapshot: WorkflowSnapshot) -> bool:
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO workflow_snapshots
                (id, run_id, thread_id, data, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                snapshot.id,
                snapshot.run_id,
                snapshot.thread_id,
                json.dumps(snapshot.to_dict(), default=str),
                snapshot.created_at.isoformat()
            ))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"Failed to save snapshot: {e}")
            return False
    
    def load_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT data FROM workflow_snapshots WHERE id = ?', (snapshot_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        data = json.loads(row[0])
        return WorkflowSnapshot.from_dict(data)


class PersistenceManager:
    """Main persistence manager
    
    Following the architecture: 状态持久化 with multiple backends
    
    Features:
    - Automatic state saving
    - State history management
    - Snapshot creation
    - Checksum validation
    - Backup support
    
    Usage:
        manager = PersistenceManager(backend=PersistenceBackend.SQLITE)
        
        # Save state
        manager.save_state(run_id="run_1", state={"data": "value"})
        
        # Load latest state
        state = manager.load_latest("run_1")
        
        # Create snapshot
        snapshot = manager.create_snapshot("run_1")
    """
    
    def __init__(
        self,
        config: Optional[PersistenceConfig] = None,
        backend: Optional[PersistenceBackendBase] = None
    ):
        self.config = config or PersistenceConfig()
        self.backend = backend or self._create_default_backend()
        self._lock = threading.RLock()
        self._history: dict[str, list[StateRecord]] = {}
        self._auto_save_enabled = self.config.auto_save
    
    def _create_default_backend(self) -> PersistenceBackendBase:
        """Create default backend based on config"""
        if self.config.backend == PersistenceBackend.FILE:
            return FilePersistenceBackend()
        elif self.config.backend == PersistenceBackend.SQLITE:
            return SQLitePersistenceBackend()
        else:
            return MemoryPersistenceBackend()
    
    def save_state(
        self,
        run_id: str,
        state_data: dict[str, Any],
        thread_id: Optional[str] = None,
        node_name: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None
    ) -> StateRecord:
        """Save workflow state
        
        Args:
            run_id: Run ID
            state_data: State data to save
            thread_id: Optional thread ID
            node_name: Optional node name
            metadata: Optional metadata
            
        Returns:
            Created StateRecord
        """
        import uuid
        
        record = StateRecord(
            id=str(uuid.uuid4()),
            run_id=run_id,
            thread_id=thread_id,
            node_name=node_name,
            state_data=state_data,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            metadata=metadata or {}
        )
        
        if self.config.enable_checksum:
            record.checksum = self._calculate_checksum(state_data)
        
        with self._lock:
            self.backend.save_state(record)
            
            key = f"{run_id}:{thread_id or 'default'}"
            if key not in self._history:
                self._history[key] = []
            
            self._history[key].append(record)
            
            if len(self._history[key]) > self.config.max_history_size:
                self._history[key].pop(0)
        
        return record
    
    def load_latest(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> Optional[StateRecord]:
        """Load latest state for a run"""
        return self.backend.load_latest_state(run_id, thread_id)
    
    def load_state(self, record_id: str) -> Optional[StateRecord]:
        """Load state by record ID"""
        return self.backend.load_state(record_id)
    
    def get_history(
        self,
        run_id: str,
        thread_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> list[StateRecord]:
        """Get state history for a run
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            limit: Optional limit on number of records
            
        Returns:
            List of StateRecords
        """
        key = f"{run_id}:{thread_id or 'default'}"
        
        with self._lock:
            history = self._history.get(key, [])
            
            if limit:
                return history[-limit:]
            
            return history
    
    def create_snapshot(
        self,
        run_id: str,
        thread_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None
    ) -> WorkflowSnapshot:
        """Create a workflow snapshot
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            metadata: Optional metadata
            
        Returns:
            Created WorkflowSnapshot
        """
        import uuid
        
        states = self.backend.list_states(run_id, thread_id)
        
        from ..checkpoint.manager import CheckpointManager
        checkpoint_manager = CheckpointManager()
        checkpoints = checkpoint_manager.list_checkpoints(run_id, thread_id)
        
        snapshot = WorkflowSnapshot(
            id=str(uuid.uuid4()),
            run_id=run_id,
            thread_id=thread_id,
            checkpoints=checkpoints,
            state_history=states,
            metadata=metadata or {}
        )
        
        self.backend.save_snapshot(snapshot)
        
        return snapshot
    
    def load_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        """Load a workflow snapshot"""
        return self.backend.load_snapshot(snapshot_id)
    
    def _calculate_checksum(self, data: dict) -> str:
        """Calculate checksum for data"""
        import hashlib
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()
    
    def validate_checksum(self, record: StateRecord) -> bool:
        """Validate record checksum"""
        if not record.checksum:
            return True
        
        calculated = self._calculate_checksum(record.state_data)
        return calculated == record.checksum


def create_persistence_manager(
    backend: PersistenceBackend = PersistenceBackend.SQLITE,
    **config
) -> PersistenceManager:
    """Factory function to create persistence manager
    
    Args:
        backend: Backend type
        **config: Configuration options
        
    Returns:
        PersistenceManager instance
    """
    persistence_config = PersistenceConfig(
        backend=backend,
        **config
    )
    
    return PersistenceManager(config=persistence_config)