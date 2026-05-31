"""文件处理器基类。

定义所有文件处理器的抽象接口，确保一致性和可扩展性。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class HandlerCapability(Enum):
    RAW_TEXT = auto()
    BASE64_ENCODED = auto()
    OCR_TEXT = auto()
    AUDIO_TRANSCRIPTION = auto()
    VIDEO_DESCRIPTION = auto()
    METADATA = auto()


@dataclass
class FileReadResult:
    success: bool
    content: str | None = None
    error_message: str | None = None
    handler_name: str = ""
    capability_used: HandlerCapability = HandlerCapability.RAW_TEXT
    metadata: dict[str, Any] = field(default_factory=dict)
    file_size: int = 0
    file_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            'success': self.success,
            'content': self.content,
            'error_message': self.error_message,
            'handler_name': self.handler_name,
            'capability_used': self.capability_used.name,
            'metadata': self.metadata,
            'file_size': self.file_size,
            'file_type': self.file_type,
        }

    @property
    def is_success(self) -> bool:
        return self.success

    def __str__(self) -> str:
        if self.success:
            preview = (self.content[:200] + '...') if self.content and len(self.content) > 200 else self.content
            return f"FileReadResult(success=True, content_length={len(self.content) if self.content else 0})"
        return f"FileReadResult(success=False, error={self.error_message})"


@runtime_checkable
class FileHandler(Protocol):
    """文件处理器协议，定义所有处理器必须实现的方法。"""

    @property
    def name(self) -> str:
        """处理器名称。"""
        ...

    @property
    def supported_extensions(self) -> set[str]:
        """支持的文件扩展名集合。"""
        ...

    def can_handle(self, file_path: str | Path) -> bool:
        """判断此处理器是否能处理指定文件。"""
        ...

    def get_capabilities(self) -> set[HandlerCapability]:
        """返回此处理器支持的能力集合。"""
        ...

    def read(self, file_path: str | Path, **kwargs: Any) -> FileReadResult:
        """读取文件并返回结果。"""
        ...

    async def read_async(self, file_path: str | Path, **kwargs: Any) -> FileReadResult:
        """异步读取文件并返回结果。"""
        ...


class BaseFileHandler(ABC):
    """文件处理器抽象基类。"""

    def __init__(self, max_file_size: int | None = None) -> None:
        self._max_file_size = max_file_size
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    @abstractmethod
    def name(self) -> str:
        """处理器名称。"""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> set[str]:
        """支持的扩展名集合。"""
        pass

    def can_handle(self, file_path: str | Path) -> bool:
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions

    @abstractmethod
    def get_capabilities(self) -> set[HandlerCapability]:
        """返回此处理器支持的能力集合。"""
        pass

    @abstractmethod
    def _do_read(self, file_path: Path, **kwargs: Any) -> FileReadResult:
        """实际执行文件读取操作的抽象方法，子类必须实现。"""
        pass

    def _validate_file(self, file_path: Path) -> tuple[bool, str]:
        if not file_path.exists():
            return False, f"文件不存在: {file_path}"
        if not file_path.is_file():
            return False, f"路径不是文件: {file_path}"

        file_size = file_path.stat().st_size
        if self._max_file_size and file_size > self._max_file_size:
            return False, f"文件过大 ({file_size / 1024 / 1024:.2f}MB)，超过最大限制 ({self._max_file_size / 1024 / 1024:.2f}MB)"

        return True, ""

    def read(self, file_path: str | Path, **kwargs: Any) -> FileReadResult:
        path = Path(file_path)
        try:
            valid, error_msg = self._validate_file(path)
            if not valid:
                return FileReadResult(
                    success=False,
                    error_message=error_msg,
                    handler_name=self.name,
                    file_size=path.stat().st_size if path.exists() else 0,
                )

            return self._do_read(path, **kwargs)

        except Exception as e:
            self._logger.exception(f"读取文件 {file_path} 时发生错误")
            return FileReadResult(
                success=False,
                error_message=f"读取文件时发生错误: {str(e)}",
                handler_name=self.name,
                file_size=path.stat().st_size if path.exists() else 0,
            )

    async def read_async(self, file_path: str | Path, **kwargs: Any) -> FileReadResult:
        return self.read(file_path, **kwargs)

    def _create_success_result(
        self,
        content: str,
        file_path: Path,
        capability: HandlerCapability = HandlerCapability.RAW_TEXT,
        metadata: dict[str, Any] | None = None,
    ) -> FileReadResult:
        return FileReadResult(
            success=True,
            content=content,
            handler_name=self.name,
            capability_used=capability,
            metadata=metadata or {},
            file_size=file_path.stat().st_size,
            file_type=file_path.suffix.lower(),
        )

    def _create_error_result(self, error_message: str, file_path: Path | None = None) -> FileReadResult:
        return FileReadResult(
            success=False,
            error_message=error_message,
            handler_name=self.name,
            file_size=file_path.stat().st_size if file_path and file_path.exists() else 0,
        )