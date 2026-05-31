"""文本文件处理器。

支持各种文本格式文件的读取，包括代码、配置文件、数据文件等。
自动检测文件编码（UTF-8, GBK, GB2312 等）。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .base_handler import (
    BaseFileHandler,
    FileReadResult,
    HandlerCapability,
)
try:
    from ..file_types import (
        SUPPORTED_TEXT_EXTENSIONS,
        TextSubtype,
        detect_file_subtype,
    )
except ImportError:
    from file_types import (
        SUPPORTED_TEXT_EXTENSIONS,
        TextSubtype,
        detect_file_subtype,
    )

logger = logging.getLogger(__name__)


class EncodingDetector:
    BOM_MARKERS = {
        'utf-8': b'\xef\xbb\xbf',
        'utf-16-le': b'\xff\xfe',
        'utf-16-be': b'\xfe\xff',
        'utf-32-le': b'\xff\xfe\x00\x00',
        'utf-32-be': b'\x00\x00\xfe\xff',
    }

    @classmethod
    def detect(cls, raw_bytes: bytes) -> str:
        if not raw_bytes:
            return 'utf-8'

        for encoding, bom in cls.BOM_MARKERS.items():
            if raw_bytes.startswith(bom):
                return encoding.replace('-', '_').replace('_le', '-le').replace('_be', '-be')

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
            raw_bytes[:3].decode('gb2312')
            return 'gb2312'
        except UnicodeDecodeError:
            pass

        try:
            raw_bytes[:3].decode('gb18030')
            return 'gb18030'
        except UnicodeDecodeError:
            pass

        try:
            raw_bytes[:3].decode('utf-16')
            return 'utf-16'
        except UnicodeDecodeError:
            pass

        try:
            raw_bytes[:3].decode('iso-8859-1')
            return 'iso-8859-1'
        except UnicodeDecodeError:
            pass

        return 'utf-8'

    @classmethod
    def should_strip_bom(cls, encoding: str) -> bool:
        return encoding.lower() in {'utf-8', 'utf-8-sig'}


class TextFileHandler(BaseFileHandler):
    name: str = "TextFileHandler"
    supported_extensions: set[str] = SUPPORTED_TEXT_EXTENSIONS

    def __init__(self, max_file_size: int | None = None) -> None:
        super().__init__(max_file_size)

    def get_capabilities(self) -> set[HandlerCapability]:
        return {HandlerCapability.RAW_TEXT, HandlerCapability.METADATA}

    def _do_read(self, file_path: Path, **kwargs: Any) -> FileReadResult:
        try:
            raw_bytes = file_path.read_bytes()

            if len(raw_bytes) == 0:
                return self._create_success_result("", file_path)

            encoding = EncodingDetector.detect(raw_bytes)
            should_strip_bom = EncodingDetector.should_strip_bom(encoding)

            if should_strip_bom:
                bom = EncodingDetector.BOM_MARKERS.get('utf-8', b'\xef\xbb\xbf')
                if raw_bytes.startswith(bom):
                    raw_bytes = raw_bytes[len(bom):]

            try:
                content = raw_bytes.decode(encoding.replace('-', '_').replace('_le', '-le').replace('_be', '-be'))
            except (UnicodeDecodeError, LookupError):
                content = raw_bytes.decode('utf-8', errors='replace')

            content = self._normalize_line_endings(content)

            subtype = detect_file_subtype(str(file_path))
            metadata = self._extract_metadata(content, subtype)

            return self._create_success_result(
                content=content,
                file_path=file_path,
                capability=HandlerCapability.RAW_TEXT,
                metadata=metadata,
            )

        except Exception as e:
            self._logger.exception(f"读取文本文件 {file_path} 失败")
            return self._create_error_result(f"读取文本文件失败: {str(e)}", file_path)

    def _normalize_line_endings(self, content: str) -> str:
        return content.replace('\r\n', '\n').replace('\r', '\n')

    def _extract_metadata(
        self,
        content: str,
        subtype: TextSubtype | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            'line_count': content.count('\n') + 1,
            'char_count': len(content),
            'has_trailing_newline': content.endswith('\n'),
        }

        if subtype:
            metadata['subtype'] = subtype.name
            metadata['is_code'] = subtype == TextSubtype.CODE

        lines = content.split('\n')
        metadata['non_empty_lines'] = sum(1 for line in lines if line.strip())
        metadata['max_line_length'] = max((len(line) for line in lines), default=0)
        metadata['avg_line_length'] = sum(len(line) for line in lines) / len(lines) if lines else 0

        if subtype == TextSubtype.CODE:
            metadata['language'] = self._detect_language_from_content(content)

        elif subtype in {TextSubtype.JSON, TextSubtype.YAML}:
            try:
                import json
                if subtype == TextSubtype.JSON:
                    parsed = json.loads(content)
                    metadata['is_valid_json'] = True
                    metadata['json_type'] = type(parsed).__name__
                    if isinstance(parsed, dict):
                        metadata['json_key_count'] = len(parsed)
                    elif isinstance(parsed, list):
                        metadata['json_array_length'] = len(parsed)
            except (json.JSONDecodeError, ValueError):
                metadata['is_valid_json'] = False

        return metadata

    def _detect_language_from_content(self, content: str) -> str | None:
        patterns = {
            'python': [r'^\s*def\s+\w+\s*\(', r'^\s*class\s+\w+', r'^\s*import\s+\w+', r'^\s*from\s+\w+\s+import'],
            'javascript': [r'^\s*const\s+\w+\s*=', r'^\s*let\s+\w+\s*=', r'^\s*function\s+\w+\s*\(', r'=>'],
            'java': [r'^\s*public\s+(class|interface|enum)', r'^\s*private\s+', r'^\s*protected\s+'],
            'go': [r'^\s*package\s+\w+', r'^\s*func\s+\w+\s*\(', r'^\s*import\s+\('],
            'rust': [r'^\s*fn\s+\w+\s*\(', r'^\s*let\s+(mut\s+)?\w+', r'^\s*impl\s+\w+'],
            'typescript': [r'^\s*interface\s+\w+', r'^\s*type\s+\w+\s*=', r':\s*\w+\[\]'],
        }

        first_lines = '\n'.join(content.split('\n')[:20])
        for lang, lang_patterns in patterns.items():
            for pattern in lang_patterns:
                if re.search(pattern, first_lines, re.MULTILINE):
                    return lang

        return None

    def read_as_lines(self, file_path: str | Path) -> list[str]:
        result = self.read(file_path)
        if not result.success:
            return []
        return result.content.split('\n') if result.content else []

    def read_first_n_lines(self, file_path: str | Path, n: int) -> str:
        lines = self.read_as_lines(file_path)
        return '\n'.join(lines[:n])