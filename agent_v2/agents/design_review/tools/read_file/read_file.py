"""Read File Tool

Tool for reading various file types.
Follows the architecture: Tool = capability execution

Supports:
- Text files: .txt, .md, .json, .yaml, .py, .js, etc.
- Images: .jpg, .png, .gif, .webp
- Documents: .pdf, .doc, .docx, .xls, .xlsx, etc.
- Audio: .mp3, .wav, .flac
- Video: .mp4, .avi, .mkv
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig

from .file_types import FileCategory, FileTypeRegistry, detect_file_category
from .model_adapter import (
    ModelAdapter,
    ModelType,
    OutputFormat,
    ModelRegistry,
    is_multimodal_model,
    detect_model_type,
    ProcessedContent,
)
from .handlers import (
    BaseFileHandler,
    FileReadResult,
    HandlerCapability,
    TextFileHandler,
    ImageFileHandler,
    DocumentFileHandler,
    AudioFileHandler,
    VideoFileHandler,
)

logger = logging.getLogger(__name__)


class FileSizeLevel(int):
    BASIC = 1
    STANDARD = 2
    PREMIUM = 3
    ENTERPRISE = 4


FILE_SIZE_LIMITS = {
    FileSizeLevel.BASIC: 5 * 1024 * 1024,
    FileSizeLevel.STANDARD: 20 * 1024 * 1024,
    FileSizeLevel.PREMIUM: 50 * 1024 * 1024,
    FileSizeLevel.ENTERPRISE: 100 * 1024 * 1024,
}

DEFAULT_FILE_SIZE_LEVEL = FileSizeLevel.BASIC


class FileSizeConfig:
    """File size configuration for different levels"""
    
    def __init__(self, level: int = DEFAULT_FILE_SIZE_LEVEL):
        self.level = level
        self.limit = FILE_SIZE_LIMITS.get(level, FILE_SIZE_LIMITS[DEFAULT_FILE_SIZE_LEVEL])
    
    def can_read(self, file_path: str) -> bool:
        """Check if file can be read within size limits"""
        try:
            path = Path(file_path)
            if path.exists():
                return path.stat().st_size <= self.limit
            return True
        except Exception:
            return True
    
    def get_limit_display(self) -> str:
        """Get human-readable size limit"""
        size_mb = self.limit / (1024 * 1024)
        if size_mb >= 1:
            return f"{size_mb:.0f}MB"
        return f"{self.limit / 1024:.0f}KB"


class ReadFileToolConfig:
    """Configuration for read file tool"""
    
    def __init__(
        self,
        file_size_level: int = DEFAULT_FILE_SIZE_LEVEL,
        enable_oss: bool = True,
        enable_multimodal: bool = True,
        default_handler: str = "auto"
    ):
        self.file_size_config = FileSizeConfig(file_size_level)
        self.enable_oss = enable_oss
        self.enable_multimodal = enable_multimodal
        self.default_handler = default_handler
        self._handlers: dict[FileCategory, BaseFileHandler] = {}
        self._init_handlers()
    
    def _init_handlers(self):
        """Initialize file handlers"""
        self._handlers = {
            FileCategory.TEXT: TextFileHandler(),
            FileCategory.IMAGE: ImageFileHandler(),
            FileCategory.DOCUMENT: DocumentFileHandler(),
            FileCategory.AUDIO: AudioFileHandler(),
            FileCategory.VIDEO: VideoFileHandler(),
        }
    
    def get_handler(self, category: FileCategory) -> BaseFileHandler:
        """Get handler for file category"""
        return self._handlers.get(category, TextFileHandler())


class ReadFileTool(BaseTool):
    """Main read file tool
    
    Supports multiple file types with appropriate handlers.
    Can work in two modes:
    - Local mode: Read directly from file path
    - OSS mode: Read from OSS using object name
    """
    
    model_config = {"extra": "allow"}
    
    name: str = "read_file"
    description: str = """读取本地文件或OSS文件的内容。

支持两种模式：
1. 本地模式：直接读取本地文件路径
2. OSS模式：通过object_name读取OSS文件

支持文件类型：
- 文本：.txt, .md, .json, .yaml, .py, .js, .ts, .html, .css, .xml等
- 图片：.jpg, .jpeg, .png, .gif, .webp, .bmp等
- 文档：.pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx等
- 音频：.mp3, .wav, .flac, .aac, .ogg等
- 视频：.mp4, .avi, .mkv, .mov, .wmv等

参数：
- file_path: 本地文件路径（使用本地模式时）
- object_name: OSS对象名（使用OSS模式时）
- is_oss: 是否使用OSS模式（默认False）

返回：
- 文本文件：文件内容
- 图片/文档：Base64编码或处理后的内容
- 其他：状态消息
"""
    
    def __init__(self, config: ReadFileToolConfig = None):
        super().__init__()
        self.config = config or ReadFileToolConfig()
    
    def _run(
        self,
        file_path: str = None,
        object_name: str = None,
        is_oss: bool = False,
        **kwargs
    ) -> str:
        """Execute file reading
        
        Args:
            file_path: Local file path
            object_name: OSS object name
            is_oss: Whether to use OSS mode
            
        Returns:
            File content or processing result
        """
        try:
            if is_oss and object_name:
                return self._read_from_oss(object_name)
            elif file_path:
                return self._read_local_file(file_path)
            else:
                return "错误：未提供有效的文件路径或对象名"
        except Exception as e:
            logger.error(f"Read file error: {e}")
            return f"读取文件失败: {str(e)}"
    
    def _read_local_file(self, file_path: str) -> str:
        """Read local file with appropriate handler
        
        Args:
            file_path: Local file path
            
        Returns:
            Processed file content
        """
        if not self.config.file_size_config.can_read(file_path):
            return f"错误：文件超过大小限制 ({self.config.file_size_config.get_limit_display()})"
        
        category = detect_file_category(file_path)
        handler = self.config.get_handler(category)
        
        result = handler.read(file_path)
        
        if result.success:
            if category == FileCategory.IMAGE and self.config.enable_multimodal:
                return self._process_image_content(result.content, file_path)
            return result.content
        
        return f"错误：{result.error or '未知错误'}"
    
    def _read_from_oss(self, object_name: str) -> str:
        """Read file from OSS
        
        Args:
            object_name: OSS object name
            
        Returns:
            File content
        """
        try:
            from infrastructure.download import DownloadService
            
            download_service = DownloadService()
            local_path = download_service.download(object_name)
            
            return self._read_local_file(local_path)
        except ImportError:
            return "错误：OSS功能不可用"
        except Exception as e:
            return f"错误：从OSS读取失败: {str(e)}"
    
    def _process_image_content(self, content: str, file_path: str) -> str:
        """Process image content for multimodal models
        
        Args:
            content: Image content (path or base64)
            file_path: Original file path
            
        Returns:
            Processed content
        """
        model_type = detect_model_type()
        
        if model_type == ModelType.MULTIMODAL:
            adapter = ModelAdapter(model_type)
            processed = adapter.adapt(content, file_path, OutputFormat.BASE64)
            return f"[IMAGE]({processed.content})"
        
        return content


class ReadFileToolFactory:
    """Factory for creating read file tools"""
    
    @staticmethod
    def create(
        file_size_level: int = DEFAULT_FILE_SIZE_LEVEL,
        enable_oss: bool = True,
        enable_multimodal: bool = True
    ) -> ReadFileTool:
        """Create read file tool
        
        Args:
            file_size_level: File size level
            enable_oss: Enable OSS mode
            enable_multimodal: Enable multimodal processing
            
        Returns:
            ReadFileTool instance
        """
        config = ReadFileToolConfig(
            file_size_level=file_size_level,
            enable_oss=enable_oss,
            enable_multimodal=enable_multimodal
        )
        return ReadFileTool(config)


read_file_tool = ReadFileTool()