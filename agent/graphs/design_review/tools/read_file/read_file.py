"""文件读取工具。

支持两种读取模式：
1. OSS 模式：前端上传文件到 OSS，通过 object_name 读取
2. 本地模式：直接读取本地文件路径

设计要点：
- 支持多种文件类型（.txt, .md, .json, .yaml, .py, .js, .ts 等）
- 自动推断文件编码（UTF-8, GBK 等）
- 支持大文件分块读取
- 集成 OSS 下载服务，通过依赖注入获取 StorageService
"""

from __future__ import annotations

import os
import re
import json
import logging
from pathlib import Path
from typing import Literal, Any
from enum import IntEnum

from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig

from infrastructure.download import DownloadService

logger = logging.getLogger(__name__)


class FileSizeLevel(IntEnum):
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
        self.level = level
        self.custom_limit = custom_limit

    @property
    def max_size(self) -> int:
        if self.custom_limit is not None:
            return self.custom_limit
        return FILE_SIZE_LIMITS[self.level]

    @staticmethod
    def from_user_identity(user_id: str | None = None, **kwargs) -> FileSizeConfig:
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

SUPPORTED_TEXT_EXTENSIONS = {
    '.txt', '.md', '.json', '.yaml', '.yml', '.xml', '.html', '.css', '.js', '.ts',
    '.jsx', '.tsx', '.py', '.rb', '.go', '.java', '.c', '.cpp', '.h', '.hpp',
    '.cs', '.php', '.sh', '.bash', '.zsh', '.sql', '.csv', '.log', '.conf',
    '.cfg', '.ini', '.toml', '.env', '.gitignore', '.dockerfile'
}

MAX_FILE_SIZE = FILE_SIZE_LIMITS[DEFAULT_FILE_SIZE_LEVEL]


class ReadFileError(Exception):
    pass


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = """读取文件内容的工具。支持从本地路径或 OSS 读取文件。

    参数:
        file_path: 本地文件路径（如 "d:/docs/prd.md"）
        object_name: OSS 对象名称（如 "design_review/prd_v1.md"）
        mode: 读取模式，"local" 或 "oss"，默认自动检测
        file_size_level: 文件大小限制等级（1=BASIC 5MB, 2=STANDARD 20MB, 3=PREMIUM 50MB, 4=ENTERPRISE 100MB）

    返回:
        文件内容字符串，失败时返回错误信息
    """

    def __init__(
        self,
        download_service: DownloadService | None = None,
        temp_dir: str | Path | None = None,
        file_size_config: FileSizeConfig | None = None,
    ) -> None:
        super().__init__()
        self._download_service = download_service
        self._temp_dir = Path(temp_dir) if temp_dir else Path.home() / ".hgj_agent" / "temp"
        self._file_size_config = file_size_config or FileSizeConfig()

    @property
    def max_file_size(self) -> int:
        return self._file_size_config.max_size

    def _get_download_service(self) -> DownloadService:
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

    def _detect_encoding(self, raw_bytes: bytes) -> str:
        try:
            raw_bytes[:3].decode('utf-8')
            return 'utf-8'
        except UnicodeDecodeError:
            pass

        try:
            raw_bytes[:3].decode('gbk')
            return 'gbk'
        except UnicodeDecodeError:
            pass

        try:
            raw_bytes[:3].decode('utf-16')
            return 'utf-16'
        except UnicodeDecodeError:
            pass

        return 'utf-8'

    def _get_file_type(self, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        if ext in SUPPORTED_TEXT_EXTENSIONS:
            return "text"
        if ext in {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}:
            return "binary"
        return "text"

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

        target_path = object_name if object_name else file_path

        if not target_path:
            return "错误: 请提供 file_path 或 object_name 参数"

        try:
            if mode == "local":
                return self._read_local_file(target_path)
            elif mode == "oss":
                return self._read_from_oss(target_path)
            else:
                if Path(target_path).exists():
                    return self._read_local_file(target_path)
                elif self._is_oss_path(target_path):
                    return self._read_from_oss(target_path)
                else:
                    raise ReadFileError(f"文件路径无效: {target_path}，本地文件不存在且不是有效的 OSS 路径")
        except ReadFileError as e:
            return f"读取文件失败: {str(e)}"
        except Exception as e:
            logger.exception("读取文件时发生未预期的错误")
            return f"读取文件时发生错误: {str(e)}"

    def _read_local_file(self, file_path: str) -> str:
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

        file_type = self._get_file_type(str(path))
        if file_type == "binary":
            raise ReadFileError(
                f"不支持读取二进制文件类型: {path.suffix}。"
                f"请转换为文本格式后重试"
            )

        try:
            content = path.read_text(encoding='utf-8')
            return content
        except UnicodeDecodeError:
            raw_bytes = path.read_bytes()
            encoding = self._detect_encoding(raw_bytes)
            content = raw_bytes.decode(encoding)
            return content
        except Exception as e:
            raise ReadFileError(f"读取文件失败: {str(e)}")

    def _read_from_oss(self, object_name: str) -> str:
        if object_name.startswith("oss://"):
            object_name = object_name[5:]
        elif object_name.startswith("aliyun://"):
            object_name = object_name[8:]

        self._ensure_temp_dir()
        local_path = self._temp_dir / object_name.replace("/", "_")

        try:
            service = self._get_download_service()
            result = service.download(object_name, str(local_path))

            content = self._read_local_file(str(local_path))
            return content
        finally:
            if local_path.exists():
                try:
                    local_path.unlink()
                except Exception:
                    pass

    def _ensure_temp_dir(self) -> None:
        self._temp_dir.mkdir(parents=True, exist_ok=True)


read_file_tool = ReadFileTool()