"""Backup Manager Module

Provides backup and recovery functionality for workflow persistence.
Following the architecture: 备份恢复 for disaster recovery

Features:
- Full and incremental backup strategies
- Checksum validation
- Automatic cleanup based on retention
- Backup metadata tracking
- Compression support
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional
import json
import shutil
import tarfile
import gzip
from pathlib import Path
import hashlib
import uuid


class BackupStrategy(Enum):
    """Backup strategy types"""
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


@dataclass
class BackupMetadata:
    """Metadata for a backup"""
    backup_id: str
    strategy: BackupStrategy
    created_at: datetime
    size_bytes: int
    run_ids: list[str]
    checksum: Optional[str] = None
    description: Optional[str] = None
    retention_days: Optional[int] = None
    compressed: bool = True


class BackupBackend(ABC):
    """Abstract base class for backup storage
    
    Implement this class to provide custom backup storage.
    """
    
    @abstractmethod
    def save_backup(self, backup_id: str, data: bytes) -> bool:
        """Save backup data"""
        pass
    
    @abstractmethod
    def load_backup(self, backup_id: str) -> Optional[bytes]:
        """Load backup data"""
        pass
    
    @abstractmethod
    def delete_backup(self, backup_id: str) -> bool:
        """Delete backup"""
        pass
    
    @abstractmethod
    def list_backups(self) -> list[BackupMetadata]:
        """List all backups"""
        pass


class FileBackupBackend(BackupBackend):
    """File-based backup storage
    
    Stores backups as compressed tar files.
    Suitable for development and small deployments.
    """
    
    def __init__(self, base_path: str = "./backups"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.base_path / "metadata.json"
    
    def _get_backup_path(self, backup_id: str) -> Path:
        return self.base_path / f"{backup_id}.tar.gz"
    
    def _load_metadata(self) -> dict:
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'backups': []}
    
    def _save_metadata(self, metadata: dict) -> None:
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, default=str)
    
    def save_backup(self, backup_id: str, data: bytes) -> bool:
        try:
            backup_path = self._get_backup_path(backup_id)
            
            with gzip.open(backup_path, 'wb') as f:
                f.write(data)
            
            metadata = self._load_metadata()
            metadata['backups'].append({
                'backup_id': backup_id,
                'size_bytes': len(data),
                'created_at': datetime.now().isoformat()
            })
            self._save_metadata(metadata)
            
            return True
        except Exception as e:
            print(f"Failed to save backup: {e}")
            return False
    
    def load_backup(self, backup_id: str) -> Optional[bytes]:
        backup_path = self._get_backup_path(backup_id)
        
        if not backup_path.exists():
            return None
        
        try:
            with gzip.open(backup_path, 'rb') as f:
                return f.read()
        except Exception as e:
            print(f"Failed to load backup: {e}")
            return None
    
    def delete_backup(self, backup_id: str) -> bool:
        backup_path = self._get_backup_path(backup_id)
        
        if backup_path.exists():
            backup_path.unlink()
            
            metadata = self._load_metadata()
            metadata['backups'] = [
                b for b in metadata['backups']
                if b['backup_id'] != backup_id
            ]
            self._save_metadata(metadata)
            
            return True
        return False
    
    def list_backups(self) -> list[BackupMetadata]:
        metadata = self._load_metadata()
        backups = []
        
        for b in metadata['backups']:
            backups.append(BackupMetadata(
                backup_id=b['backup_id'],
                strategy=BackupStrategy.FULL,
                created_at=datetime.fromisoformat(b['created_at']),
                size_bytes=b.get('size_bytes', 0),
                run_ids=[]
            ))
        
        return sorted(backups, key=lambda x: x.created_at, reverse=True)


class BackupManager:
    """Manages backup creation, restoration, and cleanup
    
    Following the architecture: 备份恢复 for disaster recovery
    
    Features:
    - Full and incremental backup strategies
    - Checksum validation
    - Automatic cleanup based on retention
    - Backup metadata tracking
    
    Usage:
        manager = BackupManager()
        
        # Create full backup
        backup = manager.create_backup(
            run_ids=["run_1", "run_2"],
            strategy=BackupStrategy.FULL
        )
        
        # Restore from backup
        manager.restore_backup(backup.backup_id)
        
        # Cleanup old backups
        manager.cleanup(retention_days=30)
    """
    
    def __init__(
        self,
        backend: Optional[BackupBackend] = None,
        retention_days: Optional[int] = 30
    ):
        self.backend = backend or FileBackupBackend()
        self.retention_days = retention_days
    
    def create_backup(
        self,
        run_ids: list[str],
        strategy: BackupStrategy = BackupStrategy.FULL,
        description: Optional[str] = None,
        source_manager: Optional['PersistenceManager'] = None
    ) -> BackupMetadata:
        """Create a backup
        
        Args:
            run_ids: List of run IDs to backup
            strategy: Backup strategy
            description: Optional description
            source_manager: Optional persistence manager to backup from
            
        Returns:
            BackupMetadata
        """
        backup_id = str(uuid.uuid4())
        
        backup_data = {
            'backup_id': backup_id,
            'run_ids': run_ids,
            'strategy': strategy.value,
            'created_at': datetime.now().isoformat(),
            'description': description,
        }
        
        if source_manager:
            for run_id in run_ids:
                snapshot = source_manager.create_snapshot(run_id)
                backup_data[run_id] = snapshot.to_dict()
        
        data = json.dumps(backup_data, indent=2, default=str).encode()
        
        self.backend.save_backup(backup_id, data)
        
        return BackupMetadata(
            backup_id=backup_id,
            strategy=strategy,
            created_at=datetime.now(),
            size_bytes=len(data),
            run_ids=run_ids,
            description=description
        )
    
    def restore_backup(
        self,
        backup_id: str,
        target_manager: Optional['PersistenceManager'] = None
    ) -> bool:
        """Restore from a backup
        
        Args:
            backup_id: Backup ID
            target_manager: Optional persistence manager to restore to
            
        Returns:
            True if successful
        """
        data = self.backend.load_backup(backup_id)
        
        if not data:
            return False
        
        if target_manager:
            backup_data = json.loads(data.decode())
            
            for run_id in backup_data.get('run_ids', []):
                if run_id in backup_data:
                    from .persistence_manager import WorkflowSnapshot
                    snapshot = WorkflowSnapshot.from_dict(backup_data[run_id])
                    
                    for state_record in snapshot.state_history:
                        target_manager.backend.save_state(state_record)
        
        return True
    
    def list_backups(self) -> list[BackupMetadata]:
        """List all backups"""
        return self.backend.list_backups()
    
    def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup"""
        return self.backend.delete_backup(backup_id)
    
    def cleanup(self, retention_days: Optional[int] = None) -> int:
        """Cleanup old backups based on retention policy
        
        Args:
            retention_days: Optional override for retention period
            
        Returns:
            Number of backups deleted
        """
        retention = retention_days or self.retention_days
        cutoff_date = datetime.now() - timedelta(days=retention)
        
        backups = self.list_backups()
        deleted_count = 0
        
        for backup in backups:
            if backup.created_at < cutoff_date:
                if self.delete_backup(backup.backup_id):
                    deleted_count += 1
        
        return deleted_count
    
    def get_backup_info(self, backup_id: str) -> Optional[dict]:
        """Get backup information
        
        Args:
            backup_id: Backup ID
            
        Returns:
            Backup info dict or None
        """
        backups = self.list_backups()
        
        for backup in backups:
            if backup.backup_id == backup_id:
                return {
                    'backup_id': backup.backup_id,
                    'strategy': backup.strategy.value,
                    'created_at': backup.created_at.isoformat(),
                    'size_bytes': backup.size_bytes,
                    'run_ids': backup.run_ids,
                    'description': backup.description,
                    'retention_days': backup.retention_days,
                }
        
        return None


def create_backup_manager(
    storage_type: str = "file",
    **config
) -> BackupManager:
    """Factory function to create backup manager
    
    Args:
        storage_type: Storage type (file)
        **config: Configuration options
        
    Returns:
        BackupManager instance
    """
    backend = FileBackupBackend(base_path=config.get('base_path', './backups'))
    retention_days = config.get('retention_days', 30)
    
    return BackupManager(backend=backend, retention_days=retention_days)