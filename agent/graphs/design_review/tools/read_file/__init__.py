"""文件读取工具模块。

支持多种文件类型的读取，包括文本、图片、文档、音频、视频等。
内置多模态模型适配功能，可根据模型类型自动选择最佳处理方式。
"""

from .read_file import (
    ReadFileTool,
    ReadFileError,
    FileSizeConfig,
    FileSizeLevel,
    FILE_SIZE_LIMITS,
    DEFAULT_FILE_SIZE_LEVEL,
    read_file_tool,
    HandlerRegistry,
)

from .file_types import (
    FileCategory,
    TextSubtype,
    ImageSubtype,
    DocumentSubtype,
    FileTypeRegistry,
    SUPPORTED_TEXT_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_DOCUMENT_EXTENSIONS,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    detect_file_category,
    detect_file_subtype,
    is_supported_file,
)

from .model_adapter import (
    ModelAdapter,
    ModelType,
    OutputFormat,
    ModelCapability,
    ModelRegistry,
    FormatSelector,
    ProcessedContent,
    detect_model_type,
    is_multimodal_model,
    register_custom_model,
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

from .oss_adapter import (
    OSSFileIDAdapter,
    FileMetadata,
    get_oss_file_id_adapter,
    reset_oss_file_id_adapter,
)

__all__ = [
    'ReadFileTool',
    'ReadFileError',
    'FileSizeConfig',
    'FileSizeLevel',
    'FILE_SIZE_LIMITS',
    'DEFAULT_FILE_SIZE_LEVEL',
    'read_file_tool',
    'HandlerRegistry',
    'FileCategory',
    'TextSubtype',
    'ImageSubtype',
    'DocumentSubtype',
    'FileTypeRegistry',
    'SUPPORTED_TEXT_EXTENSIONS',
    'SUPPORTED_IMAGE_EXTENSIONS',
    'SUPPORTED_DOCUMENT_EXTENSIONS',
    'SUPPORTED_AUDIO_EXTENSIONS',
    'SUPPORTED_VIDEO_EXTENSIONS',
    'detect_file_category',
    'detect_file_subtype',
    'is_supported_file',
    'ModelAdapter',
    'ModelType',
    'OutputFormat',
    'ModelCapability',
    'ModelRegistry',
    'FormatSelector',
    'ProcessedContent',
    'detect_model_type',
    'is_multimodal_model',
    'register_custom_model',
    'BaseFileHandler',
    'FileReadResult',
    'HandlerCapability',
    'TextFileHandler',
    'ImageFileHandler',
    'DocumentFileHandler',
    'AudioFileHandler',
    'VideoFileHandler',
    'OSSFileIDAdapter',
    'FileMetadata',
    'get_oss_file_id_adapter',
    'reset_oss_file_id_adapter',
]