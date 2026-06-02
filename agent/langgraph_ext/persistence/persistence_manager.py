"""Persistence Manager Module

Manages workflow state persistence with multiple backend support.
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

from ..checkpoint.manager import Checkpoint, CheckpointTrigger


class PersistenceBackend(Enum):
    MEMORY = "memory"
    FILE = "file"
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    REDIS = "redis"
    S3 = "s3"


@dataclass
class StateRecord:
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
        from ..checkpoint.manager import Checkpoint
        
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
    """Abstract base class for persistence backends."""
    
    @abstractmethod
    def save_state(self, record: StateRecord) -> bool:
        pass
    
    @abstractmethod
    def load_state(self, record_id: str) -> Optional[StateRecord]:
        pass
    
    @abstractmethod
    def load_latest_state(self, run_id: str, thread_id: Optional[str] = None) -> Optional[StateRecord]:
        pass
    
    @abstractmethod
    def delete_state(self, record_id: str) -> bool:
        pass
    
    @abstractmethod
    def list_states(self, run_id: str, thread_id: Optional[str] = None) -> list[StateRecord]:
        pass
    
    @abstractmethod
    def save_snapshot(self, snapshot: WorkflowSnapshot) -> bool:
        pass
    
    @abstractmethod
    def load_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        pass


class FilePersistenceBackend(PersistenceBackendBase):
    """File-based persistence backend."""
    
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
    """SQLite-based persistence backend."""
    
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
                checksum TEXT,
                metadata TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_run_thread
            ON state_records(run_id, thread_id)
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workflow_snapshots (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                thread_id TEXT,
                snapshot_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_state(self, record: StateRecord) -> bool:
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                '''INSERT OR REPLACE INTO state_records 
                   (id, run_id, thread_id, node_name, state_data, created_at, updated_at, version, checksum, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    record.id,
                    record.run_id,
                    record.thread_id,
                    record.node_name,
                    json.dumps(record.state_data, default=str),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.version,
                    record.checksum,
                    json.dumps(record.metadata, default=str)
                )
            )
            
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
        
        if row:
            return StateRecord(
                id=row[0],
                run_id=row[1],
                thread_id=row[2],
                node_name=row[3],
                state_data=json.loads(row[4]),
                created_at=datetime.fromisoformat(row[5]),
                updated_at=datetime.fromisoformat(row[6]),
                version=row[7],
                checksum=row[8],
                metadata=json.loads(row[9]) if row[9] else {}
            )
        
        return None
    
    def load_latest_state(self, run_id: str, thread_id: Optional[str] = None) -> Optional[StateRecord]:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id:
            cursor.execute(
                '''SELECT * FROM state_records 
                   WHERE run_id = ? AND thread_id = ?
                   ORDER BY created_at DESC LIMIT 1''',
                (run_id, thread_id)
            )
        else:
            cursor.execute(
                '''SELECT * FROM state_records 
                   WHERE run_id = ?
                   ORDER BY created_at DESC LIMIT 1''',
                (run_id,)
            )
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return StateRecord(
                id=row[0],
                run_id=row[1],
                thread_id=row[2],
                node_name=row[3],
                state_data=json.loads(row[4]),
                created_at=datetime.fromisoformat(row[5]),
                updated_at=datetime.fromisoformat(row[6]),
                version=row[7],
                checksum=row[8],
                metadata=json.loads(row[9]) if row[9] else {}
            )
        
        return None
    
    def delete_state(self, record_id: str) -> bool:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM state_records WHERE id = ?', (record_id,))
        conn.commit()
        conn.close()
        
        return True
    
    def list_states(self, run_id: str, thread_id: Optional[str] = None) -> list[StateRecord]:
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id:
            cursor.execute(
                '''SELECT * FROM state_records 
                   WHERE run_id = ? AND thread_id = ?
                   ORDER BY created_at ASC''',
                (run_id, thread_id)
            )
        else:
            cursor.execute(
                '''SELECT * FROM state_records 
                   WHERE run_id = ?
                   ORDER BY created_at ASC''',
                (run_id,)
            )
        
        rows = cursor.fetchall()
        conn.close()
        
        states = []
        for row in rows:
            states.append(StateRecord(
                id=row[0],
                run_id=row[1],
                thread_id=row[2],
                node_name=row[3],
                state_data=json.loads(row[4]),
                created_at=datetime.fromisoformat(row[5]),
                updated_at=datetime.fromisoformat(row[6]),
                version=row[7],
                checksum=row[8],
                metadata=json.loads(row[9]) if row[9] else {}
            ))
        
        return states
    
    def save_snapshot(self, snapshot: WorkflowSnapshot) -> bool:
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                '''INSERT OR REPLACE INTO workflow_snapshots 
                   (id, run_id, thread_id, snapshot_data, created_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    snapshot.id,
                    snapshot.run_id,
                    snapshot.thread_id,
                    json.dumps(snapshot.to_dict(), default=str),
                    snapshot.created_at.isoformat(),
                    json.dumps(snapshot.metadata, default=str)
                )
            )
            
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
        
        cursor.execute('SELECT snapshot_data FROM workflow_snapshots WHERE id = ?', (snapshot_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            data = json.loads(row[0])
            return WorkflowSnapshot.from_dict(data)
        
        return None


class PersistenceManager:
    """Manages workflow state persistence across multiple backends.
    
    Features:
    - Multiple backend support
    - Automatic state saving
    - State history tracking
    - Data compression
    - Checksum validation
    """
    
    def __init__(
        self,
        config: Optional[PersistenceConfig] = None,
        backend: Optional[PersistenceBackendBase] = None
    ):
        self.config = config or PersistenceConfig()
        self.backend = backend or self._create_default_backend()
        self._lock = threading.RLock()
        self._state_cache: dict[str, StateRecord] = {}
        self._save_callbacks: list[callable] = []
        self._load_callbacks: list[callable] = []
    
    def _create_default_backend(self) -> PersistenceBackendBase:
        """Create default backend based on config."""
        if self.config.backend == PersistenceBackend.FILE:
            return FilePersistenceBackend()
        elif self.config.backend == PersistenceBackend.SQLITE:
            return SQLitePersistenceBackend()
        elif self.config.backend == PersistenceBackend.MEMORY:
            return MemoryPersistenceBackend()
        else:
            return SQLitePersistenceBackend()
    
    def save_state(
        self,
        state: dict[str, Any],
        run_id: str,
        thread_id: Optional[str] = None,
        node_name: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None
    ) -> str:
        """Save workflow state.
        
        Args:
            state: Current workflow state
            run_id: Run ID
            thread_id: Optional thread ID
            node_name: Optional node name
            metadata: Optional metadata
            
        Returns:
            State record ID
        """
        import hashlib
        import uuid
        
        record_id = str(uuid.uuid4())
        
        state_data = state
        if self.config.compress_data:
            state_json = json.dumps(state, default=str)
            compressed = gzip.compress(state_json.encode())
            state_data = {'_compressed': True, '_data': base64.b64encode(compressed).decode()}
        
        checksum = None
        if self.config.enable_checksum:
            state_str = json.dumps(state, sort_keys=True, default=str)
            checksum = hashlib.sha256(state_str.encode()).hexdigest()
        
        record = StateRecord(
            id=record_id,
            run_id=run_id,
            thread_id=thread_id,
            node_name=node_name,
            state_data=state_data,
            checksum=checksum,
            metadata=metadata or {}
        )
        
        with self._lock:
            self.backend.save_state(record)
            self._state_cache[record_id] = record
        
        for callback in self._save_callbacks:
            try:
                callback(record)
            except Exception:
                pass
        
        return record_id
    
    def load_state(self, record_id: str) -> Optional[dict[str, Any]]:
        """Load workflow state.
        
        Args:
            record_id: State record ID
            
        Returns:
            State dict or None
        """
        with self._lock:
            if record_id in self._state_cache:
                record = self._state_cache[record_id]
            else:
                record = self.backend.load_state(record_id)
                if record:
                    self._state_cache[record_id] = record
        
        if not record:
            return None
        
        state_data = record.state_data
        if isinstance(state_data, dict) and state_data.get('_compressed'):
            compressed = base64.b64decode(state_data['_data'])
            decompressed = gzip.decompress(compressed)
            state_data = json.loads(decompressed.decode())
        
        for callback in self._load_callbacks:
            try:
                callback(record, state_data)
            except Exception:
                pass
        
        return state_data
    
    def load_latest_state(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Load the latest state for a run.
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            
        Returns:
            State dict or None
        """
        record = self.backend.load_latest_state(run_id, thread_id)
        
        if not record:
            return None
        
        return self.load_state(record.id)
    
    def create_snapshot(
        self,
        run_id: str,
        thread_id: Optional[str] = None,
        checkpoints: Optional[list[Checkpoint]] = None
    ) -> str:
        """Create a workflow snapshot.
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            checkpoints: Optional list of checkpoints to include
            
        Returns:
            Snapshot ID
        """
        import uuid
        
        snapshot_id = str(uuid.uuid4())
        
        states = self.backend.list_states(run_id, thread_id)
        
        snapshot = WorkflowSnapshot(
            id=snapshot_id,
            run_id=run_id,
            thread_id=thread_id,
            checkpoints=checkpoints or [],
            state_history=states,
            metadata={'created_at': datetime.now().isoformat()}
        )
        
        self.backend.save_snapshot(snapshot)
        
        return snapshot_id
    
    def load_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        """Load a workflow snapshot.
        
        Args:
            snapshot_id: Snapshot ID
            
        Returns:
            WorkflowSnapshot or None
        """
        return self.backend.load_snapshot(snapshot_id)
    
    def register_save_callback(self, callback: callable) -> None:
        """Register a callback to be called after state save."""
        self._save_callbacks.append(callback)
    
    def register_load_callback(self, callback: callable) -> None:
        """Register a callback to be called after state load."""
        self._load_callbacks.append(callback)
    
    def cleanup_old_states(
        self,
        run_id: str,
        thread_id: Optional[str] = None,
        keep_count: int = 10
    ) -> int:
        """Clean up old state records.
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            keep_count: Number of states to keep
            
        Returns:
            Number of states deleted
        """
        with self._lock:
            states = self.backend.list_states(run_id, thread_id)
            
            if len(states) <= keep_count:
                return 0
            
            deleted = 0
            to_delete = states[:-keep_count]
            
            for state in to_delete:
                if self.backend.delete_state(state.id):
                    deleted += 1
                    if state.id in self._state_cache:
                        del self._state_cache[state.id]
            
            return deleted
    
    def clear_cache(self) -> None:
        """Clear the state cache."""
        with self._lock:
            self._state_cache.clear()


class MemoryPersistenceBackend(PersistenceBackendBase):
    """In-memory persistence backend for testing."""
    
    def __init__(self):
        self._states: dict[str, StateRecord] = {}
        self._snapshots: dict[str, WorkflowSnapshot] = {}
        self._indices: dict[str, dict] = {}
    
    def save_state(self, record: StateRecord) -> bool:
        self._states[record.id] = record
        
        key = f"{record.run_id}:{record.thread_id or 'default'}"
        if key not in self._indices:
            self._indices[key] = {'states': [], 'latest': None}
        
        self._indices[key]['states'].append(record.id)
        self._indices[key]['latest'] = record.id
        
        return True
    
    def load_state(self, record_id: str) -> Optional[StateRecord]:
        return self._states.get(record_id)
    
    def load_latest_state(self, run_id: str, thread_id: Optional[str] = None) -> Optional[StateRecord]:
        key = f"{run_id}:{thread_id or 'default'}"
        index = self._indices.get(key, {})
        
        latest_id = index.get('latest')
        if latest_id:
            return self._states.get(latest_id)
        
        return None
    
    def delete_state(self, record_id: str) -> bool:
        if record_id in self._states:
            del self._states[record_id]
            return True
        return False
    
    def list_states(self, run_id: str, thread_id: Optional[str] = None) -> list[StateRecord]:
        key = f"{run_id}:{thread_id or 'default'}"
        index = self._indices.get(key, {})
        
        states = []
        for state_id in index.get('states', []):
            if state_id in self._states:
                states.append(self._states[state_id])
        
        return states
    
    def save_snapshot(self, snapshot: WorkflowSnapshot) -> bool:
        self._snapshots[snapshot.id] = snapshot
        return True
    
    def load_snapshot(self, snapshot_id: str) -> Optional[WorkflowSnapshot]:
        return self._snapshots.get(snapshot_id)


def create_persistence_manager(
    backend: str = "sqlite",
    **kwargs
) -> PersistenceManager:
    """Factory function to create a persistence manager.
    
    Args:
        backend: Backend type ('memory', 'file', 'sqlite')
        **kwargs: Backend-specific configuration
        
    Returns:
        PersistenceManager instance
    """
    config = PersistenceConfig(
        backend=PersistenceBackend(backend),
        connection_string=kwargs.get('connection_string'),
        auto_save=kwargs.get('auto_save', True),
        compress_data=kwargs.get('compress_data', True)
    )
    
    if backend == "memory":
        return PersistenceManager(config, MemoryPersistenceBackend())
    elif backend == "file":
        return PersistenceManager(config, FilePersistenceBackend(kwargs.get('base_path', './persistence')))
    elif backend == "sqlite":
        return PersistenceManager(config, SQLitePersistenceBackend(kwargs.get('db_path', './persistence.db')))
    else:
        raise ValueError(f"Unknown backend: {backend}")