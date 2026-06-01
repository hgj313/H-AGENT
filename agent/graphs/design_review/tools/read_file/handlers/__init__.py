"""文件处理器模块。

遵循单一职责原则，不同文件类型由专门的处理器处理。
"""

from .base_handler import BaseFileHandler, FileReadResult, HandlerCapability
from .text_handler import TextFileHandler
from .image_handler import ImageFileHandler
from .document_handler import DocumentFileHandler
from .audio_handler import AudioFileHandler
from .video_handler import VideoFileHandler

__all__ = [
    'BaseFileHandler',
    'FileReadResult', 
    'HandlerCapability',
    'TextFileHandler',
    'ImageFileHandler',
    'DocumentFileHandler',
    'AudioFileHandler',
    'VideoFileHandler',
]