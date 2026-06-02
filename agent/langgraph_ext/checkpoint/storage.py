"""Checkpoint Storage Module

Provides storage backends for checkpoint persistence.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
import json
import os
import shutil
from pathlib import Path


@dataclass
class CheckpointMetadata:
    checkpoint_id: str
    run_id: str
    thread_id: Optional[str] = None
    node_name: Optional[str] = None
    trigger: str = "manual"
    created_at: datetime = None
    description: Optional[str] = None
    version: str = "1.0"
    parent_checkpoint_id: Optional[str] = None
    tags: list = None
    metadata: dict = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.tags is None:
            self.tags = []
        if self.metadata is None:
            self.metadata = {}


class CheckpointStorage(ABC):
    """Abstract base class for checkpoint storage."""
    
    @abstractmethod
    def save(self, checkpoint) -> bool:
        """Save a checkpoint."""
        pass
    
    @abstractmethod
    def load(self, checkpoint_id: str):
        """Load a checkpoint by ID."""
        pass
    
    @abstractmethod
    def load_latest(self, run_id: str, thread_id: Optional[str] = None):
        """Load the latest checkpoint for a run."""
        pass
    
    @abstractmethod
    def list_checkpoints(self, run_id: str, thread_id: Optional[str] = None):
        """List all checkpoints for a run."""
        pass
    
    @abstractmethod
    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        pass
    
    @abstractmethod
    def exists(self, checkpoint_id: str) -> bool:
        """Check if a checkpoint exists."""
        pass


class FileCheckpointStorage(CheckpointStorage):
    """File-based checkpoint storage.
    
    Stores checkpoints as JSON files in a directory structure.
    """
    
    def __init__(
        self,
        base_path: str = "./checkpoints",
        create_dirs: bool = True
    ):
        self.base_path = Path(base_path)
        if create_dirs:
            self.base_path.mkdir(parents=True, exist_ok=True)
    
    def _get_checkpoint_path(self, checkpoint_id: str) -> Path:
        """Get the file path for a checkpoint."""
        return self.base_path / f"{checkpoint_id}.json"
    
    def _get_index_path(self, run_id: str, thread_id: Optional[str] = None) -> Path:
        """Get the index file path for a run."""
        if thread_id:
            return self.base_path / run_id / f"{thread_id}_index.json"
        return self.base_path / run_id / "index.json"
    
    def save(self, checkpoint) -> bool:
        """Save a checkpoint to file."""
        try:
            checkpoint_path = self._get_checkpoint_path(checkpoint.id)
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(checkpoint.to_dict(), f, indent=2, default=str)
            
            self._update_index(checkpoint)
            
            return True
        except Exception as e:
            print(f"Failed to save checkpoint: {e}")
            return False
    
    def _update_index(self, checkpoint) -> None:
        """Update the index file with new checkpoint."""
        run_id = checkpoint.metadata.run_id
        thread_id = checkpoint.metadata.thread_id
        index_path = self._get_index_path(run_id, thread_id)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        
        index_data = {}
        if index_path.exists():
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
        
        if 'checkpoints' not in index_data:
            index_data['checkpoints'] = []
        
        index_data['checkpoints'].append({
            'id': checkpoint.id,
            'node_name': checkpoint.metadata.node_name,
            'trigger': checkpoint.metadata.trigger.value,
            'created_at': checkpoint.metadata.created_at.isoformat(),
            'description': checkpoint.metadata.description
        })
        
        index_data['latest'] = checkpoint.id
        
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2)
    
    def load(self, checkpoint_id: str):
        """Load a checkpoint from file."""
        from .manager import Checkpoint, CheckpointMetadata, CheckpointTrigger
        
        checkpoint_path = self._get_checkpoint_path(checkpoint_id)
        if not checkpoint_path.exists():
            return None
        
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return Checkpoint.from_dict(data)
    
    def load_latest(self, run_id: str, thread_id: Optional[str] = None):
        """Load the latest checkpoint for a run."""
        index_path = self._get_index_path(run_id, thread_id)
        
        if not index_path.exists():
            return None
        
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        
        latest_id = index_data.get('latest')
        if latest_id:
            return self.load(latest_id)
        
        return None
    
    def list_checkpoints(self, run_id: str, thread_id: Optional[str] = None):
        """List all checkpoints for a run."""
        from .manager import Checkpoint, CheckpointMetadata, CheckpointTrigger
        
        index_path = self._get_index_path(run_id, thread_id)
        
        if not index_path.exists():
            return []
        
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        
        checkpoints = []
        for cp_info in index_data.get('checkpoints', []):
            cp = self.load(cp_info['id'])
            if cp:
                checkpoints.append(cp)
        
        return checkpoints
    
    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint file."""
        checkpoint_path = self._get_checkpoint_path(checkpoint_id)
        
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            return True
        
        return False
    
    def exists(self, checkpoint_id: str) -> bool:
        """Check if a checkpoint exists."""
        return self._get_checkpoint_path(checkpoint_id).exists()
    
    def cleanup(self, run_id: str, thread_id: Optional[str] = None) -> int:
        """Remove all checkpoints for a run."""
        run_path = self.base_path / run_id
        if run_path.exists():
            shutil.rmtree(run_path)
            return 1
        return 0


class MemoryCheckpointStorage(CheckpointStorage):
    """In-memory checkpoint storage for testing.
    
    Warning: Data is lost when the process exits.
    """
    
    def __init__(self):
        self._checkpoints: dict[str, Any] = {}
        self._indices: dict[str, dict] = {}
    
    def save(self, checkpoint) -> bool:
        """Save a checkpoint to memory."""
        self._checkpoints[checkpoint.id] = checkpoint.to_dict()
        
        run_id = checkpoint.metadata.run_id
        thread_id = checkpoint.metadata.thread_id
        key = f"{run_id}:{thread_id or 'default'}"
        
        if key not in self._indices:
            self._indices[key] = {'checkpoints': [], 'latest': None}
        
        self._indices[key]['checkpoints'].append(checkpoint.id)
        self._indices[key]['latest'] = checkpoint.id
        
        return True
    
    def load(self, checkpoint_id: str):
        from .manager import Checkpoint
        
        data = self._checkpoints.get(checkpoint_id)
        if data:
            return Checkpoint.from_dict(data)
        return None
    
    def load_latest(self, run_id: str, thread_id: Optional[str] = None):
        """Load the latest checkpoint."""
        key = f"{run_id}:{thread_id or 'default'}"
        index = self._indices.get(key, {})
        latest_id = index.get('latest')
        
        if latest_id:
            return self.load(latest_id)
        return None
    
    def list_checkpoints(self, run_id: str, thread_id: Optional[str] = None):
        from .manager import Checkpoint
        
        key = f"{run_id}:{thread_id or 'default'}"
        index = self._indices.get(key, {})
        
        checkpoints = []
        for cp_id in index.get('checkpoints', []):
            cp = self.load(cp_id)
            if cp:
                checkpoints.append(cp)
        
        return checkpoints
    
    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint from memory."""
        if checkpoint_id in self._checkpoints:
            del self._checkpoints[checkpoint_id]
            return True
        return False
    
    def exists(self, checkpoint_id: str) -> bool:
        """Check if checkpoint exists in memory."""
        return checkpoint_id in self._checkpoints
    
    def clear(self) -> None:
        """Clear all checkpoints from memory."""
        self._checkpoints.clear()
        self._indices.clear()


class SQLiteCheckpointStorage(CheckpointStorage):
    """SQLite-based checkpoint storage.
    
    Provides persistent storage with query capabilities.
    """
    
    def __init__(self, db_path: str = "./checkpoints.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize the database schema."""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS checkpoint_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                thread_id TEXT,
                checkpoint_id TEXT NOT NULL,
                node_name TEXT,
                trigger TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, thread_id, checkpoint_id)
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_run_thread
            ON checkpoint_index(run_id, thread_id)
        ''')
        
        conn.commit()
        conn.close()
    
    def save(self, checkpoint) -> bool:
        """Save a checkpoint to SQLite."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                'INSERT OR REPLACE INTO checkpoints (id, data, created_at) VALUES (?, ?, ?)',
                (checkpoint.id, json.dumps(checkpoint.to_dict(), default=str), datetime.now().isoformat())
            )
            
            cursor.execute(
                '''INSERT OR IGNORE INTO checkpoint_index 
                   (run_id, thread_id, checkpoint_id, node_name, trigger, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (
                    checkpoint.metadata.run_id,
                    checkpoint.metadata.thread_id,
                    checkpoint.id,
                    checkpoint.metadata.node_name,
                    checkpoint.metadata.trigger.value,
                    checkpoint.metadata.created_at.isoformat()
                )
            )
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"Failed to save checkpoint to SQLite: {e}")
            return False
    
    def load(self, checkpoint_id: str):
        from .manager import Checkpoint
        
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT data FROM checkpoints WHERE id = ?', (checkpoint_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Checkpoint.from_dict(json.loads(row[0]))
        
        return None
    
    def load_latest(self, run_id: str, thread_id: Optional[str] = None):
        """Load the latest checkpoint for a run."""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id:
            cursor.execute(
                '''SELECT checkpoint_id FROM checkpoint_index 
                   WHERE run_id = ? AND thread_id = ?
                   ORDER BY created_at DESC LIMIT 1''',
                (run_id, thread_id)
            )
        else:
            cursor.execute(
                '''SELECT checkpoint_id FROM checkpoint_index 
                   WHERE run_id = ?
                   ORDER BY created_at DESC LIMIT 1''',
                (run_id,)
            )
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self.load(row[0])
        
        return None
    
    def list_checkpoints(self, run_id: str, thread_id: Optional[str] = None):
        from .manager import Checkpoint
        
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id:
            cursor.execute(
                '''SELECT checkpoint_id FROM checkpoint_index 
                   WHERE run_id = ? AND thread_id = ?
                   ORDER BY created_at ASC''',
                (run_id, thread_id)
            )
        else:
            cursor.execute(
                '''SELECT checkpoint_id FROM checkpoint_index 
                   WHERE run_id = ?
                   ORDER BY created_at ASC''',
                (run_id,)
            )
        
        rows = cursor.fetchall()
        conn.close()
        
        checkpoints = []
        for row in rows:
            cp = self.load(row[0])
            if cp:
                checkpoints.append(cp)
        
        return checkpoints
    
    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint from SQLite."""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM checkpoints WHERE id = ?', (checkpoint_id,))
            cursor.execute('DELETE FROM checkpoint_index WHERE checkpoint_id = ?', (checkpoint_id,))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception:
            return False
    
    def exists(self, checkpoint_id: str) -> bool:
        """Check if checkpoint exists in SQLite."""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM checkpoints WHERE id = ?', (checkpoint_id,))
        exists = cursor.fetchone() is not None
        
        conn.close()
        return exists
    
    def query_by_tag(self, tag: str) -> list:
        """Query checkpoints by tag."""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT data FROM checkpoints', ())
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            data = json.loads(row[0])
            if tag in data.get('metadata', {}).get('tags', []):
                from .manager import Checkpoint
                results.append(Checkpoint.from_dict(data))
        
        return results


def create_checkpoint_storage(
    backend: str = "memory",
    **kwargs
) -> CheckpointStorage:
    """Factory function to create a checkpoint storage backend.
    
    Args:
        backend: Storage backend type ('memory', 'file', 'sqlite')
        **kwargs: Backend-specific configuration
        
    Returns:
        CheckpointStorage instance
    """
    if backend == "memory":
        return MemoryCheckpointStorage()
    elif backend == "file":
        return FileCheckpointStorage(
            base_path=kwargs.get('base_path', './checkpoints')
        )
    elif backend == "sqlite":
        return SQLiteCheckpointStorage(
            db_path=kwargs.get('db_path', './checkpoints.db')
        )
    else:
        raise ValueError(f"Unknown storage backend: {backend}")