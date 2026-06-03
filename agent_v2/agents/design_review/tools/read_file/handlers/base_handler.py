"""Base File Handler

Abstract base class for file handlers.
Following the architecture:单一职责原则
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from pathlib import Path


class HandlerCapability(Enum):
    """Handler capability flags"""
    READ_TEXT = "read_text"
    READ_BINARY = "read_binary"
    READ_STREAMING = "read_streaming"
    SUPPORT_LARGE_FILE = "support_large_file"


@dataclass
class FileReadResult:
    """File read result"""
    success: bool
    content: str
    error: Optional[str] = None
    metadata: Optional[dict] = None


class BaseFileHandler(ABC):
    """Abstract base class for file handlers
    
    All file handlers should inherit from this class
    and implement the read method.
    """
    
    name: str = "base"
    supported_extensions: set = set()
    
    def __init__(self):
        self.capabilities = self._get_capabilities()
    
    @abstractmethod
    def _read_impl(self, file_path: str) -> FileReadResult:
        """Internal read implementation
        
        Args:
            file_path: File path to read
            
        Returns:
            FileReadResult
        """
        pass
    
    def read(self, file_path: str) -> FileReadResult:
        """Read file with validation
        
        Args:
            file_path: File path
            
        Returns:
            FileReadResult
        """
        path = Path(file_path)
        
        if not path.exists():
            return FileReadResult(
                success=False,
                content="",
                error=f"文件不存在: {file_path}"
            )
        
        if not path.is_file():
            return FileReadResult(
                success=False,
                content="",
                error=f"路径不是文件: {file_path}"
            )
        
        if not self.can_handle(file_path):
            return FileReadResult(
                success=False,
                content="",
                error=f"不支持的文件类型: {path.suffix}"
            )
        
        return self._read_impl(file_path)
    
    def can_handle(self, file_path: str) -> bool:
        """Check if handler can handle this file
        
        Args:
            file_path: File path
            
        Returns:
            True if can handle
        """
        path = Path(file_path)
        return path.suffix.lower() in self.supported_extensions
    
    def _get_capabilities(self) -> set[HandlerCapability]:
        """Get handler capabilities
        
        Returns:
            Set of capabilities
        """
        return {HandlerCapability.READ_TEXT}
    
    def get_metadata(self, file_path: str) -> dict:
        """Get file metadata
        
        Args:
            file_path: File path
            
        Returns:
            Metadata dict
        """
        path = Path(file_path)
        
        if not path.exists():
            return {}
        
        stat = path.stat()
        
        return {
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "extension": path.suffix,
            "name": path.name,
        }