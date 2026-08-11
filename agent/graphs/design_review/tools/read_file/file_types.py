"""文件类型检测与分类模块。

提供文件类型枚举、扩展名映射、文件大小配置等功能。
遵循单一职责原则，专注于文件类型的识别和分类。
"""

from __future__ import annotations

import os
from enum import Enum, auto
from pathlib import Path
from typing import Final


class FileCategory(Enum):
    TEXT = auto()
    IMAGE = auto()
    DOCUMENT = auto()
    AUDIO = auto()
    VIDEO = auto()
    ARCHIVE = auto()
    UNKNOWN = auto()


class TextSubtype(Enum):
    PLAIN = auto()
    MARKDOWN = auto()
    JSON = auto()
    YAML = auto()
    XML = auto()
    HTML = auto()
    CODE = auto()
    CONFIG = auto()
    DATA = auto()
    OTHER = auto()


class ImageSubtype(Enum):
    RASTER = auto()
    VECTOR = auto()


class DocumentSubtype(Enum):
    PDF = auto()
    OFFICE_WORD = auto()
    OFFICE_EXCEL = auto()
    OFFICE_POWERPOINT = auto()
    OTHER = auto()


class ModelCapability(Enum):
    TEXT_ONLY = auto()
    VISION = auto()
    AUDIO = auto()
    MULTIMODAL = auto()


SUPPORTED_TEXT_EXTENSIONS: Final[set[str]] = {
    '.txt', '.md', '.markdown',
    '.json', '.jsonl',
    '.yaml', '.yml',
    '.xml',
    '.html', '.htm', '.xhtml',
    '.css', '.scss', '.sass', '.less',
    '.js', '.mjs', '.cjs',
    '.ts', '.tsx', '.mts', '.cts',
    '.jsx',
    '.py', '.pyw', '.pyx',
    '.rb', '.rake',
    '.go',
    '.java', '.class',
    '.c', '.h',
    '.cpp', '.cc', '.cxx', '.hpp', '.hxx',
    '.cs',
    '.php', '.phtml',
    '.sh', '.bash', '.zsh', '.fish',
    '.ps1', '.bat', '.cmd',
    '.sql',
    '.r', '.R',
    '.lua',
    '.swift',
    '.kt', '.kts',
    '.rs',
    '.scala', '.sc',
    '.pl', '.pm',
    '.hs',
    '.clj', '.cljs', '.cljc',
    '.erl', '.hrl',
    '.ex', '.exs',
    '.fs', '.fsx',
    '.vb',
    '.coffee',
    '.dart',
    '.groovy',
    '.gradle',
}

SUPPORTED_CODE_EXTENSIONS: Final[set[str]] = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h',
    '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala',
    '.html', '.css', '.sql', '.sh', '.lua', '.r', '.m', '.F', '.f',
}

SUPPORTED_CONFIG_EXTENSIONS: Final[set[str]] = {
    '.conf', '.cfg', '.ini', '.toml', '.env', '.properties',
    '.gitignore', '.dockerignore', '.editorconfig',
    '.eslintrc', '.prettierrc', '.babelrc',
    '.npmrc', '.yarnrc',
    '.htaccess', '.nginx',
}

SUPPORTED_DATA_EXTENSIONS: Final[set[str]] = {
    '.csv', '.tsv', '.dat', '.log', '.xml', '.json',
}

SUPPORTED_IMAGE_EXTENSIONS: Final[set[str]] = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
    '.webp', '.ico', '.svg', '.heic', '.heif', '.avif',
    '.raw', '.cr2', '.nef', '.arw', '.dng',
}

SUPPORTED_DOCUMENT_EXTENSIONS: Final[set[str]] = {
    '.pdf',
    '.doc', '.docx',
    '.xls', '.xlsx',
    '.ppt', '.pptx',
    '.odt', '.ods', '.odp',
    '.rtf', '.tex',
    '.epub', '.mobi', '.azw',
}

SUPPORTED_AUDIO_EXTENSIONS: Final[set[str]] = {
    '.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a',
    '.opus', '.ape', '.alac', '.aiff',
}

SUPPORTED_VIDEO_EXTENSIONS: Final[set[str]] = {
    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
    '.m4v', '.mpg', '.mpeg', '.3gp', '.ogv',
}

SUPPORTED_ARCHIVE_EXTENSIONS: Final[set[str]] = {
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz',
    '.tar.gz', '.tgz', '.tar.bz2',
}


class FileTypeRegistry:
    _instance: FileTypeRegistry | None = None

    def __new__(cls) -> FileTypeRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._extension_to_category = {}
            cls._instance._extension_to_subtype = {}
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if not getattr(self, '_initialized', False):
            self._initialize_mappings()
            self._initialized = True

    def _initialize_mappings(self) -> None:
        for ext in SUPPORTED_TEXT_EXTENSIONS:
            self._extension_to_category[ext] = FileCategory.TEXT
            if ext in SUPPORTED_CODE_EXTENSIONS:
                self._extension_to_subtype[ext] = TextSubtype.CODE
            elif ext in {'.json', '.jsonl'}:
                self._extension_to_subtype[ext] = TextSubtype.JSON
            elif ext in {'.yaml', '.yml'}:
                self._extension_to_subtype[ext] = TextSubtype.YAML
            elif ext in {'.xml'}:
                self._extension_to_subtype[ext] = TextSubtype.XML
            elif ext in {'.html', '.htm', '.xhtml'}:
                self._extension_to_subtype[ext] = TextSubtype.HTML
            elif ext in {'.md', '.markdown'}:
                self._extension_to_subtype[ext] = TextSubtype.MARKDOWN
            elif ext in SUPPORTED_CONFIG_EXTENSIONS:
                self._extension_to_subtype[ext] = TextSubtype.CONFIG
            elif ext in SUPPORTED_DATA_EXTENSIONS:
                self._extension_to_subtype[ext] = TextSubtype.DATA
            else:
                self._extension_to_subtype[ext] = TextSubtype.OTHER

        for ext in SUPPORTED_IMAGE_EXTENSIONS:
            self._extension_to_category[ext] = FileCategory.IMAGE
            if ext in {'.svg', '.ai', '.eps', '.svgz'}:
                self._extension_to_subtype[ext] = ImageSubtype.VECTOR
            else:
                self._extension_to_subtype[ext] = ImageSubtype.RASTER

        for ext in SUPPORTED_DOCUMENT_EXTENSIONS:
            self._extension_to_category[ext] = FileCategory.DOCUMENT
            if ext == '.pdf':
                self._extension_to_subtype[ext] = DocumentSubtype.PDF
            elif ext in {'.doc', '.docx'}:
                self._extension_to_subtype[ext] = DocumentSubtype.OFFICE_WORD
            elif ext in {'.xls', '.xlsx'}:
                self._extension_to_subtype[ext] = DocumentSubtype.OFFICE_EXCEL
            elif ext in {'.ppt', '.pptx'}:
                self._extension_to_subtype[ext] = DocumentSubtype.OFFICE_POWERPOINT
            else:
                self._extension_to_subtype[ext] = DocumentSubtype.OTHER

        for ext in SUPPORTED_AUDIO_EXTENSIONS:
            self._extension_to_category[ext] = FileCategory.AUDIO

        for ext in SUPPORTED_VIDEO_EXTENSIONS:
            self._extension_to_category[ext] = FileCategory.VIDEO

        for ext in SUPPORTED_ARCHIVE_EXTENSIONS:
            self._extension_to_category[ext] = FileCategory.ARCHIVE

    def get_category(self, file_path: str | Path) -> FileCategory:
        ext = Path(file_path).suffix.lower()
        return self._extension_to_category.get(ext, FileCategory.UNKNOWN)

    def get_subtype(self, file_path: str | Path) -> TextSubtype | ImageSubtype | DocumentSubtype | None:
        ext = Path(file_path).suffix.lower()
        return self._extension_to_subtype.get(ext)

    def is_supported(self, file_path: str | Path) -> bool:
        return self.get_category(file_path) != FileCategory.UNKNOWN

    def get_mime_type(self, file_path: str | Path) -> str:
        ext = Path(file_path).suffix.lower()
        mime_types: dict[str, str] = {
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.markdown': 'text/markdown',
            '.json': 'application/json',
            '.jsonl': 'application/jsonl',
            '.yaml': 'application/x-yaml',
            '.yml': 'application/x-yaml',
            '.xml': 'application/xml',
            '.html': 'text/html',
            '.htm': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.ts': 'application/typescript',
            '.py': 'text/x-python',
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml',
            '.mp3': 'audio/mpeg',
            '.mp4': 'video/mp4',
            '.zip': 'application/zip',
        }
        return mime_types.get(ext, 'application/octet-stream')

    def get_supported_extensions(self, category: FileCategory | None = None) -> set[str]:
        if category is None:
            return set(self._extension_to_category.keys())
        return {ext for ext, cat in self._extension_to_category.items() if cat == category}


def detect_file_category(file_path: str | Path) -> FileCategory:
    return FileTypeRegistry().get_category(file_path)


def detect_file_subtype(file_path: str | Path) -> TextSubtype | ImageSubtype | DocumentSubtype | None:
    return FileTypeRegistry().get_subtype(file_path)


def is_supported_file(file_path: str | Path) -> bool:
    return FileTypeRegistry().is_supported(file_path)