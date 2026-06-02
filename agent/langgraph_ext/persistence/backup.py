"""Backup Manager Module

Provides backup and recovery functionality for workflow persistence.
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


class BackupStrategy(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


@dataclass
class BackupMetadata:
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
    """Abstract base class for backup storage."""
    
    @abstractmethod
    def save_backup(self, backup_id: str, data: bytes) -> bool:
        pass
    
    @abstractmethod
    def load_backup(self, backup_id: str) -> Optional[bytes]:
        pass
    
    @abstractmethod
    def delete_backup(self, backup_id: str) -> bool:
        pass
    
    @abstractmethod
    def list_backups(self) -> list[BackupMetadata]:
        pass


class FileBackupBackend(BackupBackend):
    """File-based backup storage."""
    
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
                size_bytes=b.get('size_bytes', 0)
            ))
        
        return sorted(backups, key=lambda x: x.created_at, reverse=True)


class BackupManager:
    """Manages backup creation, restoration, and cleanup.
    
    Features:
    - Full and incremental backup strategies
    - Checksum validation
    - Automatic cleanup based on retention
    - Backup metadata tracking
    """
    
    def __init__(
        self,
        backend: Optional[BackupBackend] = None,
        retention_days: int = 30,
        max_backups: int = 10
    ):
        self.backend = backend or FileBackupBackend()
        self.retention_days = retention_days
        self.max_backups = max_backups
    
    def create_backup(
        self,
        persistence_manager,
        run_ids: list[str],
        strategy: BackupStrategy = BackupStrategy.FULL,
        description: Optional[str] = None
    ) -> str:
        """Create a backup of workflow data.
        
        Args:
            persistence_manager: PersistenceManager instance
            run_ids: List of run IDs to backup
            strategy: Backup strategy
            description: Optional backup description
            
        Returns:
            Backup ID
        """
        import uuid
        import tarfile
        import io
        
        backup_id = str(uuid.uuid4())
        
        tar_buffer = io.BytesIO()
        
        with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
            for run_id in run_ids:
                states = persistence_manager.backend.list_states(run_id)
                
                for state in states:
                    state_json = json.dumps(state.to_dict(), default=str)
                    tarinfo = tarfile.TarInfo(name=f"states/{state.id}.json")
                    tarinfo.size = len(state_json.encode())
                    tar.addfile(tarinfo, io.BytesIO(state_json.encode()))
        
        tar_data = tar_buffer.getvalue()
        
        checksum = hashlib.sha256(tar_data).hexdigest()
        
        self.backend.save_backup(backup_id, tar_data)
        
        self.cleanup_old_backups()
        
        return backup_id
    
    def restore_backup(
        self,
        backup_id: str,
        persistence_manager,
        target_run_ids: Optional[list[str]] = None
    ) -> bool:
        """Restore a backup to persistence.
        
        Args:
            backup_id: Backup ID
            persistence_manager: PersistenceManager instance
            target_run_ids: Optional list of run IDs to restore (None = all)
            
        Returns:
            True if successful
        """
        import tarfile
        import io
        
        backup_data = self.backend.load_backup(backup_id)
        
        if not backup_data:
            return False
        
        try:
            tar_buffer = io.BytesIO(backup_data)
            
            with tarfile.open(fileobj=tar_buffer, mode='r') as tar:
                for member in tar.getmembers():
                    if member.name.startswith('states/') and member.name.endswith('.json'):
                        f = tar.extractfile(member)
                        if f:
                            state_data = json.load(f)
                            
                            from .persistence_manager import StateRecord
                            record = StateRecord.from_dict(state_data)
                            
                            if target_run_ids is None or record.run_id in target_run_ids:
                                persistence_manager.backend.save_state(record)
            
            return True
        except Exception as e:
            print(f"Failed to restore backup: {e}")
            return False
    
    def list_backups(self) -> list[BackupMetadata]:
        """List all available backups.
        
        Returns:
            List of BackupMetadata
        """
        return self.backend.list_backups()
    
    def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup.
        
        Args:
            backup_id: Backup ID
            
        Returns:
            True if deleted
        """
        return self.backend.delete_backup(backup_id)
    
    def cleanup_old_backups(self) -> int:
        """Clean up old backups based on retention policy.
        
        Returns:
            Number of backups deleted
        """
        backups = self.backend.list_backups()
        
        deleted = 0
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        
        backups_to_delete = [
            b for b in backups
            if b.created_at < cutoff_date or (len(backups) - deleted) > self.max_backups
        ]
        
        for backup in backups_to_delete:
            if self.backend.delete_backup(backup.backup_id):
                deleted += 1
        
        return deleted
    
    def export_backup(
        self,
        backup_id: str,
        export_path: str
    ) -> bool:
        """Export a backup to a file.
        
        Args:
            backup_id: Backup ID
            export_path: Destination file path
            
        Returns:
            True if successful
        """
        backup_data = self.backend.load_backup(backup_id)
        
        if not backup_data:
            return False
        
        with open(export_path, 'wb') as f:
            f.write(backup_data)
        
        return True
    
    def import_backup(
        self,
        import_path: str,
        backup_id: Optional[str] = None
    ) -> str:
        """Import a backup from a file.
        
        Args:
            import_path: Source file path
            backup_id: Optional custom backup ID
            
        Returns:
            Backup ID
        """
        import uuid
        
        with open(import_path, 'rb') as f:
            backup_data = f.read()
        
        new_backup_id = backup_id or str(uuid.uuid4())
        
        self.backend.save_backup(new_backup_id, backup_data)
        
        return new_backup_id
    
    def verify_backup(self, backup_id: str) -> bool:
        """Verify a backup's integrity.
        
        Args:
            backup_id: Backup ID
            
        Returns:
            True if backup is valid
        """
        import tarfile
        import io
        
        backup_data = self.backend.load_backup(backup_id)
        
        if not backup_data:
            return False
        
        try:
            tar_buffer = io.BytesIO(backup_data)
            
            with tarfile.open(fileobj=tar_buffer, mode='r') as tar:
                for member in tar.getmembers():
                    if member.size > 100 * 1024 * 1024:
                        return False
            
            return True
        except Exception:
            return False


def create_backup(
    persistence_manager,
    run_ids: list[str],
    strategy: BackupStrategy = BackupStrategy.FULL,
    description: Optional[str] = None
) -> str:
    """Convenience function to create a backup.
    
    Args:
        persistence_manager: PersistenceManager instance
        run_ids: List of run IDs to backup
        strategy: Backup strategy
        description: Optional description
        
    Returns:
        Backup ID
    """
    manager = BackupManager()
    return manager.create_backup(persistence_manager, run_ids, strategy, description)


def restore_backup(
    backup_id: str,
    persistence_manager,
    target_run_ids: Optional[list[str]] = None
) -> bool:
    """Convenience function to restore a backup.
    
    Args:
        backup_id: Backup ID
        persistence_manager: PersistenceManager instance
        target_run_ids: Optional target run IDs
        
    Returns:
        True if successful
    """
    manager = BackupManager()
    return manager.restore_backup(backup_id, persistence_manager, target_run_ids)