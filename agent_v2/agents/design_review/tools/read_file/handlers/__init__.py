"""File Handlers Module

Provides handlers for different file types.
Following the architecture:按文件类型模块化处理
"""

from .base_handler import (
    BaseFileHandler,
    FileReadResult,
    HandlerCapability,
)

from .text_handler import TextFileHandler
from .image_handler import ImageFileHandler
from .document_handler import DocumentFileHandler
from .audio_handler import AudioFileHandler
from .video_handler import VideoFileHandler

__all__ = [
    "BaseFileHandler",
    "FileReadResult",
    "HandlerCapability",
    "TextFileHandler",
    "ImageFileHandler",
    "DocumentFileHandler",
    "AudioFileHandler",
    "VideoFileHandler",
]