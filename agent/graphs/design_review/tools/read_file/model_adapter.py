"""多模态模型适配器模块。

根据调用模型的类型自动选择最合适的文件处理方式和输出格式。
支持多种输出模式：Base64、URL、Binary、FileID。

架构设计：
1. 模型能力注册表 - 定义各模型支持的能力
2. 格式选择器 - 根据模型能力和文件类型选择最优格式
3. 模型适配接口 - 统一的模型交互接口
"""

from __future__ import annotations

import logging
import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class OutputFormat(Enum):
    BASE64 = auto()
    URL = auto()
    BINARY = auto()
    FILE_ID = auto()
    TEXT = auto()
    AUTO = auto()


class ModelType(Enum):
    TEXT_ONLY = auto()
    VISION = auto()
    AUDIO = auto()
    VIDEO = auto()
    MULTIMODAL = auto()


@dataclass
class ModelCapability:
    model_type: ModelType
    supported_formats: set[OutputFormat] = field(default_factory=set)
    max_image_size: int | None = None
    preferred_max_tokens: int | None = None
    supports_streaming: bool = False
    api_endpoint: str | None = None


class ModelRegistry:
    _instance: ModelRegistry | None = None
    _capabilities: dict[str, ModelCapability] = {}

    def __new__(cls) -> ModelRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_defaults()
        return cls._instance

    def _initialize_defaults(self) -> None:
        self.register_model("gpt-4-vision-preview", ModelCapability(
            model_type=ModelType.VISION,
            supported_formats={OutputFormat.URL, OutputFormat.BASE64},
            max_image_size=20 * 1024 * 1024,
        ))

        self.register_model("gpt-4-turbo", ModelCapability(
            model_type=ModelType.MULTIMODAL,
            supported_formats={OutputFormat.URL, OutputFormat.BASE64},
        ))

        self.register_model("claude-3-opus", ModelCapability(
            model_type=ModelType.MULTIMODAL,
            supported_formats={OutputFormat.URL, OutputFormat.BASE64},
            max_image_size=10 * 1024 * 1024,
        ))

        self.register_model("claude-3-sonnet", ModelCapability(
            model_type=ModelType.MULTIMODAL,
            supported_formats={OutputFormat.URL, OutputFormat.BASE64},
            max_image_size=10 * 1024 * 1024,
        ))

        self.register_model("claude-3-haiku", ModelCapability(
            model_type=ModelType.MULTIMODAL,
            supported_formats={OutputFormat.URL, OutputFormat.BASE64},
            max_image_size=5 * 1024 * 1024,
        ))

        self.register_model("qwen-vl-max", ModelCapability(
            model_type=ModelType.VISION,
            supported_formats={OutputFormat.URL, OutputFormat.BASE64, OutputFormat.BINARY},
            max_image_size=20 * 1024 * 1024,
        ))

        self.register_model("qwen-vl-plus", ModelCapability(
            model_type=ModelType.VISION,
            supported_formats={OutputFormat.URL, OutputFormat.BASE64, OutputFormat.BINARY},
            max_image_size=10 * 1024 * 1024,
        ))

        self.register_model("qwen-audio-turbo", ModelCapability(
            model_type=ModelType.AUDIO,
            supported_formats={OutputFormat.BINARY, OutputFormat.URL},
        ))

        for model in ["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo", "claude-2", "claude-2.1"]:
            self.register_model(model, ModelCapability(
                model_type=ModelType.TEXT_ONLY,
                supported_formats={OutputFormat.TEXT},
            ))

        for model in ["text-davinci-003", "code-davinci-002"]:
            self.register_model(model, ModelCapability(
                model_type=ModelType.TEXT_ONLY,
                supported_formats={OutputFormat.TEXT},
            ))

    def register_model(self, model_name: str, capability: ModelCapability) -> None:
        self._capabilities[model_name.lower()] = capability

    def get_capability(self, model_name: str) -> ModelCapability | None:
        model_lower = model_name.lower()

        if model_lower in self._capabilities:
            return self._capabilities[model_lower]

        for registered_model, cap in self._capabilities.items():
            if registered_model in model_lower or model_lower in registered_model:
                return cap

        if any(keyword in model_lower for keyword in ["vision", "vl", "gpt-4-vision"]):
            return ModelCapability(
                model_type=ModelType.VISION,
                supported_formats={OutputFormat.URL, OutputFormat.BASE64},
            )

        if any(keyword in model_lower for keyword in ["audio", "whisper", "tts"]):
            return ModelCapability(
                model_type=ModelType.AUDIO,
                supported_formats={OutputFormat.BINARY, OutputFormat.URL},
            )

        if any(keyword in model_lower for keyword in ["qwen", "llava", "minigpt4", "multimodal"]):
            return ModelCapability(
                model_type=ModelType.MULTIMODAL,
                supported_formats={OutputFormat.URL, OutputFormat.BASE64, OutputFormat.BINARY},
            )

        return None

    def is_vision_model(self, model_name: str) -> bool:
        cap = self.get_capability(model_name)
        return cap is not None and cap.model_type in (ModelType.VISION, ModelType.MULTIMODAL)

    def is_audio_model(self, model_name: str) -> bool:
        cap = self.get_capability(model_name)
        return cap is not None and cap.model_type == ModelType.AUDIO

    def is_text_only_model(self, model_name: str) -> bool:
        cap = self.get_capability(model_name)
        return cap is None or cap.model_type == ModelType.TEXT_ONLY


class FormatSelector:
    @staticmethod
    def select_format(
        model_name: str,
        file_category: str,
        file_size: int,
        preferred_format: OutputFormat | None = None,
    ) -> OutputFormat:
        capability = ModelRegistry().get_capability(model_name)

        if preferred_format and preferred_format != OutputFormat.AUTO:
            if capability is None or preferred_format in capability.supported_formats:
                return preferred_format

        if capability is None:
            return FormatSelector._default_for_category(file_category, file_size)

        available = capability.supported_formats
        if not available:
            return FormatSelector._default_for_category(file_category, file_size)

        if OutputFormat.URL in available:
            return OutputFormat.URL

        if file_category == "IMAGE":
            if file_size > 10 * 1024 * 1024 and OutputFormat.BINARY in available:
                return OutputFormat.BINARY

        for format_pref in [OutputFormat.BASE64, OutputFormat.BINARY, OutputFormat.TEXT]:
            if format_pref in available:
                return format_pref

        return available.pop()

    @staticmethod
    def _default_for_category(category: str, file_size: int) -> OutputFormat:
        if category == "IMAGE":
            if file_size < 5 * 1024 * 1024:
                return OutputFormat.BASE64
            return OutputFormat.BINARY
        return OutputFormat.TEXT


@dataclass
class ProcessedContent:
    content: str | bytes | None
    format: OutputFormat
    file_id: str | None = None
    url: str | None = None
    base64_data: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: str | None = None

    def to_model_input(self, model_name: str) -> dict[str, Any]:
        capability = ModelRegistry().get_capability(model_name)

        if capability and capability.model_type in (ModelType.VISION, ModelType.MULTIMODAL):
            if self.format == OutputFormat.URL:
                return {"type": "image_url", "image_url": {"url": self.url}}
            elif self.format == OutputFormat.BASE64:
                return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{self.base64_data}"}}
            elif self.format == OutputFormat.BINARY and isinstance(self.content, bytes):
                import base64
                encoded = base64.b64encode(self.content).decode('ascii')
                return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
            elif self.format == OutputFormat.FILE_ID:
                return {"type": "image", "image": self.file_id}

        return {"type": "text", "text": self.content}


class ModelAdapter:
    def __init__(
        self,
        model_name: str | None = None,
        temp_dir: str | Path | None = None,
        file_service_url: str | None = None,
        oss_adapter=None,
    ) -> None:
        self._model_name = model_name or "auto"
        self._temp_dir = Path(temp_dir) if temp_dir else Path.home() / ".hgj_agent" / "temp"
        self._file_service_url = file_service_url
        self._oss_adapter = oss_adapter
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def model_name(self) -> str:
        return self._model_name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self._model_name = value

    @property
    def oss_adapter(self):
        return self._oss_adapter

    def set_oss_adapter(self, adapter) -> None:
        self._oss_adapter = adapter
        self._logger.info(f"OSS 适配器已设置: {adapter}")

    def detect_model_type(self) -> ModelType | None:
        cap = ModelRegistry().get_capability(self._model_name)
        return cap.model_type if cap else None

    def is_multimodal(self) -> bool:
        cap = ModelRegistry().get_capability(self._model_name)
        if cap is None:
            return self._model_name.lower() in ["auto", "multi"]
        return cap.model_type in (ModelType.VISION, ModelType.AUDIO, ModelType.VIDEO, ModelType.MULTIMODAL)

    def select_output_format(
        self,
        file_category: str,
        file_size: int,
        preferred: OutputFormat | None = None,
    ) -> OutputFormat:
        return FormatSelector.select_format(
            model_name=self._model_name,
            file_category=file_category,
            file_size=file_size,
            preferred_format=preferred,
        )

    def process_for_model(
        self,
        content: str | bytes,
        file_path: str | Path,
        output_format: OutputFormat,
    ) -> ProcessedContent:
        path = Path(file_path)

        if output_format == OutputFormat.BASE64 and isinstance(content, bytes):
            import base64
            encoded = base64.b64encode(content).decode('ascii')
            return ProcessedContent(
                content=encoded,
                format=OutputFormat.BASE64,
                base64_data=encoded,
                metadata={"file_name": path.name, "file_size": len(content)},
            )

        elif output_format == OutputFormat.URL:
            url = self._generate_url(path)
            return ProcessedContent(
                content=content,
                format=OutputFormat.URL,
                url=url,
                metadata={"file_name": path.name},
            )

        elif output_format == OutputFormat.FILE_ID:
            file_id = self._generate_file_id(content if isinstance(content, bytes) else content.encode())
            return ProcessedContent(
                content=content,
                format=OutputFormat.FILE_ID,
                file_id=file_id,
                metadata={"file_name": path.name, "file_id": file_id},
            )

        elif output_format == OutputFormat.BINARY:
            if isinstance(content, str):
                content = content.encode()
            return ProcessedContent(
                content=content,
                format=OutputFormat.BINARY,
                metadata={"file_name": path.name, "file_size": len(content)},
            )

        return ProcessedContent(
            content=content,
            format=OutputFormat.TEXT,
            metadata={"file_name": path.name},
        )

    def _generate_url(self, file_path: Path) -> str:
        if self._file_service_url:
            return f"{self._file_service_url}/files/{file_path.name}"

        return f"file://{file_path.absolute()}"

    def _generate_file_id(self, content: bytes, object_name: str | None = None) -> str:
        if self._oss_adapter and object_name:
            return self._oss_adapter.get_file_id(object_name)

        hash_value = hashlib.sha256(content).hexdigest()[:16]
        return f"file-{hash_value}"

    def get_signed_url_for_file_id(self, file_id: str, expire_seconds: int = 3600) -> str | None:
        if self._oss_adapter:
            return self._oss_adapter.get_signed_url(file_id, expire_seconds=expire_seconds)
        return None

    def upload_and_register(
        self,
        file_path: str | Path,
        object_name: str | None = None,
    ) -> Any:
        if not self._oss_adapter:
            raise RuntimeError("OSS 适配器未设置，请先调用 set_oss_adapter()")
        return self._oss_adapter.upload_and_register(file_path, object_name)

    def prepare_for_model(
        self,
        file_id: str,
        model_type: str = "vision",
    ) -> dict[str, Any]:
        if self._oss_adapter:
            return self._oss_adapter.prepare_for_multimodal_model(file_id, model_type)

        signed_url = self.get_signed_url_for_file_id(file_id)
        if signed_url:
            return {"type": "image_url", "image_url": {"url": signed_url}}

        return {"type": "text", "text": f"[文件ID: {file_id}]"}

    def get_supported_extensions(self) -> set[str]:
        try:
            from ..file_types import (
                SUPPORTED_TEXT_EXTENSIONS,
                SUPPORTED_IMAGE_EXTENSIONS,
                SUPPORTED_DOCUMENT_EXTENSIONS,
                SUPPORTED_AUDIO_EXTENSIONS,
            )
        except ImportError:
            from file_types import (
                SUPPORTED_TEXT_EXTENSIONS,
                SUPPORTED_IMAGE_EXTENSIONS,
                SUPPORTED_DOCUMENT_EXTENSIONS,
                SUPPORTED_AUDIO_EXTENSIONS,
            )

        cap = ModelRegistry().get_capability(self._model_name)
        if cap is None:
            return SUPPORTED_TEXT_EXTENSIONS

        extensions: set[str] = set()

        if cap.model_type in (ModelType.VISION, ModelType.MULTIMODAL):
            extensions.update(SUPPORTED_IMAGE_EXTENSIONS)
            extensions.update(SUPPORTED_DOCUMENT_EXTENSIONS)

        if cap.model_type in (ModelType.AUDIO, ModelType.MULTIMODAL):
            extensions.update(SUPPORTED_AUDIO_EXTENSIONS)

        if cap.model_type == ModelType.TEXT_ONLY or not extensions:
            extensions.update(SUPPORTED_TEXT_EXTENSIONS)

        return extensions


def detect_model_type(model_name: str) -> ModelType | None:
    return ModelRegistry().get_capability(model_name).model_type if ModelRegistry().get_capability(model_name) else None


def is_multimodal_model(model_name: str) -> bool:
    cap = ModelRegistry().get_capability(model_name)
    if cap is None:
        return model_name.lower() in ["auto", "multi", "multimodal"]
    return cap.model_type != ModelType.TEXT_ONLY


def register_custom_model(model_name: str, capability: ModelCapability) -> None:
    ModelRegistry().register_model(model_name, capability)