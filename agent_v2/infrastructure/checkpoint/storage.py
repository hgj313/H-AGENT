"""Checkpoint Storage Module

Provides storage backends for checkpoint persistence.
Following the architecture: 一级持久化 support
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
import json
import os
from pathlib import Path

from .manager import Checkpoint, CheckpointMetadata, CheckpointTrigger


class CheckpointStorage(ABC):
    """Abstract base class for checkpoint storage
    
    Implement this class to provide custom storage backends.
    """
    
    @abstractmethod
    def save(self, checkpoint: Checkpoint) -> bool:
        """Save a checkpoint
        
        Args:
            checkpoint: Checkpoint to save
            
        Returns:
            True if successful
        """
        pass
    
    @abstractmethod
    def load(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load a checkpoint by ID
        
        Args:
            checkpoint_id: Checkpoint ID
            
        Returns:
            Checkpoint or None
        """
        pass
    
    @abstractmethod
    def load_latest(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Load the latest checkpoint for a run
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            
        Returns:
            Latest Checkpoint or None
        """
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint
        
        Args:
            checkpoint_id: Checkpoint ID
            
        Returns:
            True if deleted
        """
        pass
    
    @abstractmethod
    def exists(self, checkpoint_id: str) -> bool:
        """Check if a checkpoint exists
        
        Args:
            checkpoint_id: Checkpoint ID
            
        Returns:
            True if exists
        """
        pass


class MemoryCheckpointStorage(CheckpointStorage):
    """In-memory checkpoint storage
    
    Use for testing or single-instance deployments.
    Not persistent across restarts.
    """
    
    def __init__(self):
        self._checkpoints: dict[str, Checkpoint] = {}
        self._run_index: dict[str, dict[str, list[str]]] = {}
    
    def save(self, checkpoint: Checkpoint) -> bool:
        """Save checkpoint to memory"""
        self._checkpoints[checkpoint.id] = checkpoint
        
        run_id = checkpoint.metadata.run_id
        thread_id = checkpoint.metadata.thread_id or 'default'
        
        if run_id not in self._run_index:
            self._run_index[run_id] = {}
        
        if thread_id not in self._run_index[run_id]:
            self._run_index[run_id][thread_id] = []
        
        self._run_index[run_id][thread_id].append(checkpoint.id)
        
        return True
    
    def load(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load checkpoint from memory"""
        return self._checkpoints.get(checkpoint_id)
    
    def load_latest(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Load latest checkpoint"""
        thread_id = thread_id or 'default'
        
        if run_id not in self._run_index:
            return None
        
        checkpoint_ids = self._run_index[run_id].get(thread_id, [])
        if not checkpoint_ids:
            return None
        
        return self._checkpoints.get(checkpoint_ids[-1])
    
    def list_checkpoints(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> list[Checkpoint]:
        """List all checkpoints"""
        thread_id = thread_id or 'default'
        
        if run_id not in self._run_index:
            return []
        
        checkpoint_ids = self._run_index[run_id].get(thread_id, [])
        return [
            self._checkpoints[cid]
            for cid in checkpoint_ids
            if cid in self._checkpoints
        ]
    
    def delete(self, checkpoint_id: str) -> bool:
        """Delete checkpoint from memory"""
        if checkpoint_id in self._checkpoints:
            del self._checkpoints[checkpoint_id]
            return True
        return False
    
    def exists(self, checkpoint_id: str) -> bool:
        """Check if checkpoint exists"""
        return checkpoint_id in self._checkpoints
    
    def clear(self) -> None:
        """Clear all checkpoints"""
        self._checkpoints.clear()
        self._run_index.clear()


class FileCheckpointStorage(CheckpointStorage):
    """File-based checkpoint storage
    
    Stores checkpoints as JSON files in a directory structure.
    Suitable for development and small deployments.
    
    Directory structure:
        base_path/
        ├── run_id/
        │   ├── thread_id_index.json
        │   └── checkpoint_id.json
        └── ...
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
        """Get the file path for a checkpoint"""
        return self.base_path / f"{checkpoint_id}.json"
    
    def _get_index_path(self, run_id: str, thread_id: Optional[str] = None) -> Path:
        """Get the index file path for a run"""
        if thread_id:
            return self.base_path / run_id / f"{thread_id}_index.json"
        return self.base_path / run_id / "index.json"
    
    def save(self, checkpoint: Checkpoint) -> bool:
        """Save a checkpoint to file"""
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
    
    def _update_index(self, checkpoint: Checkpoint) -> None:
        """Update the index file with new checkpoint"""
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
    
    def load(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load a checkpoint from file"""
        checkpoint_path = self._get_checkpoint_path(checkpoint_id)
        if not checkpoint_path.exists():
            return None
        
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return Checkpoint.from_dict(data)
    
    def load_latest(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Load the latest checkpoint for a run"""
        index_path = self._get_index_path(run_id, thread_id)
        
        if not index_path.exists():
            return None
        
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        
        latest_id = index_data.get('latest')
        if not latest_id:
            return None
        
        return self.load(latest_id)
    
    def list_checkpoints(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> list[Checkpoint]:
        """List all checkpoints for a run"""
        index_path = self._get_index_path(run_id, thread_id)
        
        if not index_path.exists():
            return []
        
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        
        checkpoints = []
        for cp_info in index_data.get('checkpoints', []):
            checkpoint = self.load(cp_info['id'])
            if checkpoint:
                checkpoints.append(checkpoint)
        
        return checkpoints
    
    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint file"""
        checkpoint_path = self._get_checkpoint_path(checkpoint_id)
        
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            return True
        
        return False
    
    def exists(self, checkpoint_id: str) -> bool:
        """Check if checkpoint file exists"""
        return self._get_checkpoint_path(checkpoint_id).exists()


class SQLiteCheckpointStorage(CheckpointStorage):
    """SQLite-based checkpoint storage
    
    Provides persistent storage with query capabilities.
    Suitable for production deployments.
    """
    
    def __init__(self, db_path: str = "./checkpoints.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema"""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                thread_id TEXT,
                node_name TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_run_id
            ON checkpoints(run_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_run_thread
            ON checkpoints(run_id, thread_id)
        ''')
        
        conn.commit()
        conn.close()
    
    def save(self, checkpoint: Checkpoint) -> bool:
        """Save checkpoint to SQLite"""
        import sqlite3
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO checkpoints
                (id, run_id, thread_id, node_name, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                checkpoint.id,
                checkpoint.metadata.run_id,
                checkpoint.metadata.thread_id,
                checkpoint.metadata.node_name,
                json.dumps(checkpoint.to_dict(), default=str),
                checkpoint.metadata.created_at.isoformat()
            ))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"Failed to save checkpoint: {e}")
            return False
    
    def load(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load checkpoint from SQLite"""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT data FROM checkpoints WHERE id = ?',
            (checkpoint_id,)
        )
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        data = json.loads(row[0])
        return Checkpoint.from_dict(data)
    
    def load_latest(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Load latest checkpoint for run"""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id:
            cursor.execute('''
                SELECT data FROM checkpoints
                WHERE run_id = ? AND thread_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (run_id, thread_id))
        else:
            cursor.execute('''
                SELECT data FROM checkpoints
                WHERE run_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (run_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        data = json.loads(row[0])
        return Checkpoint.from_dict(data)
    
    def list_checkpoints(
        self,
        run_id: str,
        thread_id: Optional[str] = None
    ) -> list[Checkpoint]:
        """List all checkpoints for run"""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if thread_id:
            cursor.execute('''
                SELECT data FROM checkpoints
                WHERE run_id = ? AND thread_id = ?
                ORDER BY created_at ASC
            ''', (run_id, thread_id))
        else:
            cursor.execute('''
                SELECT data FROM checkpoints
                WHERE run_id = ?
                ORDER BY created_at ASC
            ''', (run_id,))
        
        checkpoints = []
        for row in cursor.fetchall():
            data = json.loads(row[0])
            checkpoints.append(Checkpoint.from_dict(data))
        
        conn.close()
        return checkpoints
    
    def delete(self, checkpoint_id: str) -> bool:
        """Delete checkpoint from SQLite"""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM checkpoints WHERE id = ?', (checkpoint_id,))
        
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return deleted
    
    def exists(self, checkpoint_id: str) -> bool:
        """Check if checkpoint exists"""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT 1 FROM checkpoints WHERE id = ?',
            (checkpoint_id,)
        )
        
        exists = cursor.fetchone() is not None
        conn.close()
        
        return exists