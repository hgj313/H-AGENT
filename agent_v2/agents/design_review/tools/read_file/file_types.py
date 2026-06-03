"""File Type Definitions

Defines file categories, types, and detection logic.
Following the architecture:单一职责原则
"""

from enum import Enum
from typing import Optional
from pathlib import Path


class FileCategory(Enum):
    """File category enumeration"""
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    UNKNOWN = "unknown"


class FileTypeRegistry:
    """Registry for file type mappings
    
    Manages file extensions to category mappings.
    """
    
    TEXT_EXTENSIONS = {
        '.txt', '.md', '.markdown',
        '.json', '.yaml', '.yml', '.toml',
        '.py', '.js', '.ts', '.jsx', '.tsx',
        '.java', '.c', '.cpp', '.h', '.hpp',
        '.cs', '.go', '.rs', '.rb', '.php',
        '.html', '.htm', '.css', '.scss', '.sass', '.less',
        '.xml', '.sql', '.sh', '.bash', '.zsh',
        '.properties', '.env', '.gitignore', '.dockerfile',
        '.log', '.csv', '.tsv',
    }
    
    IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp',
        '.bmp', '.ico', '.tiff', '.tif', '.svg',
        '.heic', '.heif', '.avif',
    }
    
    DOCUMENT_EXTENSIONS = {
        '.pdf', '.doc', '.docx',
        '.xls', '.xlsx', '.xlsm', '.xlsb',
        '.ppt', '.pptx', '.odp',
        '.rtf', '.odt', '.pages',
    }
    
    AUDIO_EXTENSIONS = {
        '.mp3', '.wav', '.flac', '.aac', '.ogg',
        '.m4a', '.wma', '.ape', '.alac',
    }
    
    VIDEO_EXTENSIONS = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv',
        '.flv', '.webm', '.m4v', '.mpg', '.mpeg',
    }
    
    def __init__(self):
        self._registry = {
            FileCategory.TEXT: self.TEXT_EXTENSIONS,
            FileCategory.IMAGE: self.IMAGE_EXTENSIONS,
            FileCategory.DOCUMENT: self.DOCUMENT_EXTENSIONS,
            FileCategory.AUDIO: self.AUDIO_EXTENSIONS,
            FileCategory.VIDEO: self.VIDEO_EXTENSIONS,
        }
    
    def get_category(self, extension: str) -> FileCategory:
        """Get category for file extension
        
        Args:
            extension: File extension (with or without dot)
            
        Returns:
            FileCategory
        """
        ext = extension.lower()
        if not ext.startswith('.'):
            ext = '.' + ext
        
        for category, extensions in self._registry.items():
            if ext in extensions:
                return category
        
        return FileCategory.UNKNOWN
    
    def get_extensions(self, category: FileCategory) -> set:
        """Get extensions for category
        
        Args:
            category: File category
            
        Returns:
            Set of extensions
        """
        return self._registry.get(category, set())


def detect_file_category(file_path: str) -> FileCategory:
    """Detect file category from file path
    
    Args:
        file_path: File path
        
    Returns:
        FileCategory
    """
    path = Path(file_path)
    extension = path.suffix
    
    registry = FileTypeRegistry()
    return registry.get_category(extension)


def get_file_type_info(file_path: str) -> dict:
    """Get detailed file type information
    
    Args:
        file_path: File path
        
    Returns:
        Dict with category, extension, mime_type
    """
    path = Path(file_path)
    extension = path.suffix.lower()
    
    registry = FileTypeRegistry()
    category = registry.get_category(extension)
    
    mime_types = {
        FileCategory.TEXT: 'text/plain',
        FileCategory.IMAGE: f'image/{extension[1:]}',
        FileCategory.DOCUMENT: 'application/octet-stream',
        FileCategory.AUDIO: f'audio/{extension[1:]}',
        FileCategory.VIDEO: f'video/{extension[1:]}',
        FileCategory.UNKNOWN: 'application/octet-stream',
    }
    
    return {
        'category': category.value,
        'extension': extension,
        'mime_type': mime_types.get(category, 'application/octet-stream'),
        'is_text': category == FileCategory.TEXT,
        'is_multimedia': category in {FileCategory.IMAGE, FileCategory.AUDIO, FileCategory.VIDEO},
    }