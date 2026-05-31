"""文件读取工具。

支持两种读取模式：
1. OSS 模式：前端上传文件到 OSS，通过 object_name 读取
2. 本地模式：直接读取本地文件路径

支持多种文件类型：
- 文本文件：.txt, .md, .json, .yaml, .py, .js, .ts 等
- 图片文件：.jpg, .png, .gif, .webp 等
- 文档文件：.pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx 等
- 音频文件：.mp3, .wav, .flac 等
- 视频文件：.mp4, .avi, .mkv 等

设计要点：
- 遵循单一职责原则，按文件类型模块化处理
- 自动检测文件类型并选择合适的处理器
- 支持多模态模型适配（Base64、URL、Binary、FileID）
- 支持文件大小分级配置
- 完善的类型校验、异常捕获与错误日志记录
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig

try:
    from infrastructure.download import DownloadService
except ImportError:
    DownloadService = None

try:
    from agent.graphs.design_review.tools.read_file.file_types import FileCategory, FileTypeRegistry, detect_file_category
    from agent.graphs.design_review.tools.read_file.model_adapter import (
        ModelAdapter,
        ModelType,
        OutputFormat,
        ModelRegistry,
        is_multimodal_model,
        detect_model_type,
        ProcessedContent,
    )
    from agent.graphs.design_review.tools.read_file.handlers import (
        BaseFileHandler,
        FileReadResult,
        HandlerCapability,
        TextFileHandler,
        ImageFileHandler,
        DocumentFileHandler,
        AudioFileHandler,
        VideoFileHandler,
    )
except ImportError:
    from agent.graphs.design_review.tools.read_file.file_types import FileCategory, FileTypeRegistry, detect_file_category
    from agent.graphs.design_review.tools.read_file.model_adapter import (
        ModelAdapter,
        ModelType,
        OutputFormat,
        ModelRegistry,
        is_multimodal_model,
        detect_model_type,
        ProcessedContent,
    )
    from agent.graphs.design_review.tools.read_file.handlers import (
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
    def __init__(
        self,
        level: FileSizeLevel = DEFAULT_FILE_SIZE_LEVEL,
        custom_limit: int | None = None,
    ) -> None:
        self.level = FileSizeLevel(level) if isinstance(level, int) else level
        self.custom_limit = custom_limit

    @property
    def max_size(self) -> int:
        if self.custom_limit is not None:
            return self.custom_limit
        return FILE_SIZE_LIMITS.get(self.level, FILE_SIZE_LIMITS[DEFAULT_FILE_SIZE_LEVEL])

    @staticmethod
    def from_user_identity(user_id: str | None = None, **kwargs: Any) -> FileSizeConfig:
        if kwargs.get("file_size_level"):
            level = FileSizeLevel(kwargs["file_size_level"])
            return FileSizeConfig(level=level)

        if kwargs.get("is_premium_user"):
            return FileSizeConfig(level=FileSizeLevel.PREMIUM)

        if kwargs.get("is_enterprise_user"):
            return FileSizeConfig(level=FileSizeLevel.ENTERPRISE)

        if kwargs.get("max_file_size"):
            return FileSizeConfig(custom_limit=kwargs["max_file_size"])

        return FileSizeConfig()


class ReadFileError(Exception):
    pass


class HandlerRegistry:
    _instance: HandlerRegistry | None = None
    _handlers: list[BaseFileHandler] = []

    def __new__(cls) -> HandlerRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_handlers()
        return cls._instance

    def _initialize_handlers(self) -> None:
        self._handlers = [
            TextFileHandler(),
            ImageFileHandler(),
            DocumentFileHandler(),
            AudioFileHandler(),
            VideoFileHandler(),
        ]

    def get_handler(self, file_path: str | Path) -> BaseFileHandler | None:
        for handler in self._handlers:
            if handler.can_handle(file_path):
                return handler
        return None

    def get_handler_by_category(self, category: FileCategory) -> BaseFileHandler | None:
        category_handler_map = {
            FileCategory.TEXT: TextFileHandler,
            FileCategory.IMAGE: ImageFileHandler,
            FileCategory.DOCUMENT: DocumentFileHandler,
            FileCategory.AUDIO: AudioFileHandler,
            FileCategory.VIDEO: VideoFileHandler,
        }

        handler_class = category_handler_map.get(category)
        if handler_class:
            for handler in self._handlers:
                if isinstance(handler, handler_class):
                    return handler
        return None

    def register_handler(self, handler: BaseFileHandler) -> None:
        self._handlers.append(handler)

    def get_all_capabilities(self) -> set[HandlerCapability]:
        capabilities: set[HandlerCapability] = set()
        for handler in self._handlers:
            capabilities.update(handler.get_capabilities())
        return capabilities


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = """读取文件内容的工具。支持从本地路径或 OSS 读取文件。

    参数:
        file_path: 本地文件路径（如 "d:/docs/prd.md"）
        object_name: OSS 对象名称（如 "design_review/prd_v1.md"）
        mode: 读取模式，"local" 或 "oss"，默认自动检测
        model_name: 指定的模型名称，用于确定输出格式（支持多模态模型）
        output_format: 输出格式，"auto"、"base64"、"url"、"text" 等
        file_size_level: 文件大小限制等级（1=BASIC 5MB, 2=STANDARD 20MB, 3=PREMIUM 50MB, 4=ENTERPRISE 100MB）
        enable_ocr: 是否启用 OCR 识别（图片文件）
        enable_transcription: 是否启用音频转录

    返回:
        文件内容字符串，失败时返回错误信息
    """

    def __init__(
        self,
        download_service: DownloadService | None = None,
        temp_dir: str | Path | None = None,
        file_size_config: FileSizeConfig | None = None,
        model_name: str | None = None,
        file_service_url: str | None = None,
    ) -> None:
        super().__init__()
        self._download_service = download_service
        self._temp_dir = Path(temp_dir) if temp_dir else Path.home() / ".hgj_agent" / "temp"
        self._file_size_config = file_size_config or FileSizeConfig()
        self._model_adapter = ModelAdapter(model_name=model_name, file_service_url=file_service_url)
        self._handler_registry = HandlerRegistry()
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def max_file_size(self) -> int:
        return self._file_size_config.max_size

    @property
    def model_adapter(self) -> ModelAdapter:
        return self._model_adapter

    def set_model(self, model_name: str) -> None:
        self._model_adapter.model_name = model_name
        self._logger.info(f"模型已切换为: {model_name}")

    def _get_download_service(self) -> DownloadService | None:
        if DownloadService is None:
            return None
        if self._download_service is None:
            self._download_service = DownloadService()
        return self._download_service

    def _is_oss_path(self, path: str) -> bool:
        if path.startswith("oss://") or path.startswith("aliyun://"):
            return True
        if re.match(r'^[a-zA-Z0-9_\-/\.]+$', path) and "/" in path:
            if not Path(path).exists():
                return True
        return False

    def _get_output_format(self, file_category: FileCategory, file_size: int, preferred_format: str | None) -> OutputFormat:
        format_map = {
            "auto": OutputFormat.AUTO,
            "base64": OutputFormat.BASE64,
            "url": OutputFormat.URL,
            "text": OutputFormat.TEXT,
            "binary": OutputFormat.BINARY,
            "file_id": OutputFormat.FILE_ID,
        }

        preferred = format_map.get(preferred_format.lower()) if preferred_format else OutputFormat.AUTO

        return self._model_adapter.select_output_format(
            file_category=file_category.value if hasattr(file_category, 'value') else str(file_category),
            file_size=file_size,
            preferred=preferred,
        )

    async def _arun(
        self,
        tool_input: dict[str, Any] | None = None,
        config: RunnableConfig | None = None,
        **kwargs,
    ) -> str:
        return self._run(tool_input, config, **kwargs)

    def _run(
        self,
        tool_input: dict[str, Any] | None = None,
        config: RunnableConfig | None = None,
        **kwargs,
    ) -> str:
        if tool_input is None:
            tool_input = kwargs

        file_path = tool_input.get("file_path") or ""
        object_name = tool_input.get("object_name") or ""
        mode = tool_input.get("mode", "auto")
        model_name = tool_input.get("model_name")
        output_format = tool_input.get("output_format")
        enable_ocr = tool_input.get("enable_ocr", False)
        enable_transcription = tool_input.get("enable_transcription", False)

        if model_name:
            self.set_model(model_name)

        target_path = object_name if object_name else file_path

        if not target_path:
            return "错误: 请提供 file_path 或 object_name 参数"

        try:
            if mode == "local":
                return self._read_local_file(target_path, output_format, enable_ocr, enable_transcription)
            elif mode == "oss":
                return self._read_from_oss(target_path, output_format)
            else:
                if Path(target_path).exists():
                    return self._read_local_file(target_path, output_format, enable_ocr, enable_transcription)
                elif self._is_oss_path(target_path):
                    return self._read_from_oss(target_path, output_format)
                else:
                    raise ReadFileError(f"文件路径无效: {target_path}，本地文件不存在且不是有效的 OSS 路径")
        except ReadFileError as e:
            return f"读取文件失败: {str(e)}"
        except Exception as e:
            self._logger.exception("读取文件时发生未预期的错误")
            return f"读取文件时发生错误: {str(e)}"

    def _read_local_file(
        self,
        file_path: str,
        output_format: str | None = None,
        enable_ocr: bool = False,
        enable_transcription: bool = False,
    ) -> str:
        path = Path(file_path)

        if not path.exists():
            raise ReadFileError(f"文件不存在: {file_path}")

        if not path.is_file():
            raise ReadFileError(f"路径不是文件: {file_path}")

        file_size = path.stat().st_size
        if file_size > self.max_file_size:
            raise ReadFileError(
                f"文件过大 ({file_size / 1024 / 1024:.2f}MB)，"
                f"超过最大限制 ({self.max_file_size / 1024 / 1024:.2f}MB)"
            )

        category = detect_file_category(str(path))
        handler = self._handler_registry.get_handler_by_category(category)

        if not handler:
            raise ReadFileError(f"不支持的文件类型: {path.suffix}")

        if isinstance(handler, ImageFileHandler):
            handler._enable_ocr = enable_ocr
        elif isinstance(handler, AudioFileHandler):
            handler._enable_transcription = enable_transcription

        handler._max_file_size = self.max_file_size
        result = handler.read(path)

        if not result.success:
            raise ReadFileError(result.error_message or "读取文件失败")

        output_fmt = self._get_output_format(category, file_size, output_format)
        processed = self._model_adapter.process_for_model(
            content=result.content or "",
            file_path=path,
            output_format=output_fmt,
        )

        if processed.format == OutputFormat.BASE64 and processed.base64_data:
            return self._format_image_output(path, result, processed, category)
        elif processed.format == OutputFormat.URL and processed.url:
            return self._format_url_output(path, result, processed, category)
        elif processed.format == OutputFormat.TEXT:
            return result.content or ""
        else:
            return result.content or ""

    def _format_image_output(
        self,
        path: Path,
        result: FileReadResult,
        processed: ProcessedContent,
        category: FileCategory,
    ) -> str:
        metadata = result.metadata or {}
        parts = [
            f"[图片文件: {path.name}]",
            f"[格式: {metadata.get('format', path.suffix.lstrip('.'))}]",
            f"[尺寸: {metadata.get('width', 'N/A')}x{metadata.get('height', 'N/A')}]",
            f"[Base64数据长度: {len(processed.base64_data) if processed.base64_data else 0}字符]",
            "",
        ]

        if self._model_adapter.is_multimodal():
            mime_type = metadata.get('format', 'jpeg')
            if mime_type == 'png':
                mime_type = 'image/png'
            elif mime_type == 'gif':
                mime_type = 'image/gif'
            elif mime_type == 'webp':
                mime_type = 'image/webp'
            else:
                mime_type = 'image/jpeg'

            parts.append(f"[数据格式: data:{mime_type};base64,...]")
            parts.append("")
            if processed.base64_data:
                parts.append(processed.base64_data)
        else:
            parts.append("[提示: 当前模型不支持图片输入，仅提供图片元数据]")
            parts.append(f"[模型建议: 请使用多模态模型如 gpt-4-vision-preview、claude-3-sonnet、qwen-vl-max 等]")

        return "\n".join(parts)

    def _format_url_output(
        self,
        path: Path,
        result: FileReadResult,
        processed: ProcessedContent,
        category: FileCategory,
    ) -> str:
        parts = [
            f"[文件: {path.name}]",
            f"[URL: {processed.url}]",
            f"[格式: {path.suffix.lstrip('.')}]",
        ]

        if result.metadata:
            parts.append(f"[元数据: {result.metadata}]")

        return "\n".join(parts)

    def _read_from_oss(self, object_name: str, output_format: str | None = None) -> str:
        if object_name.startswith("oss://"):
            object_name = object_name[5:]
        elif object_name.startswith("aliyun://"):
            object_name = object_name[8:]

        self._ensure_temp_dir()
        local_path = self._temp_dir / object_name.replace("/", "_")

        try:
            service = self._get_download_service()
            service.download(object_name, str(local_path))

            content = self._read_local_file(str(local_path), output_format)
            return content
        finally:
            if local_path.exists():
                try:
                    local_path.unlink()
                except Exception:
                    pass

    def _ensure_temp_dir(self) -> None:
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def get_handler_capabilities(self) -> dict[str, Any]:
        capabilities: dict[str, Any] = {}
        for handler in self._handler_registry._handlers:
            capabilities[handler.name] = {
                'extensions': list(handler.supported_extensions),
                'capabilities': [c.name for c in handler.get_capabilities()],
            }
        return capabilities

    def get_model_capabilities(self, model_name: str) -> dict[str, Any]:
        cap = ModelRegistry().get_capability(model_name)
        if not cap:
            return {'error': f'未知的模型: {model_name}'}

        return {
            'model_type': cap.model_type.name,
            'supported_formats': [f.name for f in cap.supported_formats],
            'max_image_size': cap.max_image_size,
            'supports_streaming': cap.supports_streaming,
        }


read_file_tool = ReadFileTool()