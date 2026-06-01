"""图片文件处理器。

支持各种图片格式的读取，提供 Base64 编码和 OCR 文本提取能力。
根据调用模型的类型自动选择合适的处理方式。
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image

from agent.graphs.design_review.tools.read_file.handlers.base_handler import (
    BaseFileHandler,
    FileReadResult,
    HandlerCapability,
)

logger = logging.getLogger(__name__)


class ImageFileHandler(BaseFileHandler):
    name: str = "ImageFileHandler"
    supported_extensions: set[str] = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
        '.webp', '.ico', '.heic', '.heif', '.avif',
        '.raw', '.cr2', '.nef', '.arw', '.dng',
        '.svg', '.psd',
    }

    def __init__(self, max_file_size: int | None = None, enable_ocr: bool = False) -> None:
        super().__init__(max_file_size)
        self._enable_ocr = enable_ocr

    def get_capabilities(self) -> set[HandlerCapability]:
        capabilities = {HandlerCapability.BASE64_ENCODED, HandlerCapability.METADATA}
        if self._enable_ocr:
            capabilities.add(HandlerCapability.OCR_TEXT)
        return capabilities

    def _do_read(self, file_path: Path, **kwargs: Any) -> FileReadResult:
        mode = kwargs.get('mode', 'auto')

        if mode == 'base64':
            return self._read_as_base64(file_path, **kwargs)
        elif mode == 'ocr':
            return self._read_as_ocr(file_path, **kwargs)
        elif mode == 'auto':
            return self._read_auto(file_path, **kwargs)
        else:
            return self._read_as_base64(file_path, **kwargs)

    def _read_auto(self, file_path: Path, **kwargs: Any) -> FileReadResult:
        base64_result = self._read_as_base64(file_path, **kwargs)
        if base64_result.success:
            return base64_result

        if self._enable_ocr:
            return self._read_as_ocr(file_path, **kwargs)

        return base64_result

    def _read_as_base64(self, file_path: Path, **kwargs: Any) -> FileReadResult:
        try:
            raw_bytes = file_path.read_bytes()
            
            mime_type = self._get_mime_type(file_path)
            encoded = base64.b64encode(raw_bytes).decode('ascii')
            base64_data = f"data:{mime_type};base64,{encoded}"

            metadata = self._extract_image_metadata(file_path, raw_bytes)
            metadata['mode'] = 'base64'
            metadata['base64_length'] = len(encoded)

            content = f"[图片文件: {file_path.name}]\n[格式: {metadata.get('format', 'unknown')}]\n[尺寸: {metadata.get('width', 'N/A')}x{metadata.get('height', 'N/A')}]\n[Base64数据长度: {len(encoded)}字符]\n\n{base64_data}"

            return self._create_success_result(
                content=content,
                file_path=file_path,
                capability=HandlerCapability.BASE64_ENCODED,
                metadata=metadata,
            )

        except Exception as e:
            self._logger.exception(f"读取图片文件 {file_path} 失败")
            return self._create_error_result(f"读取图片文件失败: {str(e)}", file_path)

    def _read_as_ocr(self, file_path: Path, **kwargs: Any) -> FileReadResult:
        if not self._enable_ocr:
            return self._create_error_result("OCR 功能未启用", file_path)

        try:
            import pytesseract

            image = Image.open(file_path)
            text = pytesseract.image_to_string(image, lang=kwargs.get('ocr_lang', 'chi_sim+eng'))

            metadata = self._extract_image_metadata(file_path)
            metadata['mode'] = 'ocr'
            metadata['ocr_language'] = kwargs.get('ocr_lang', 'chi_sim+eng')
            metadata['text_length'] = len(text)

            return self._create_success_result(
                content=f"[图片OCR识别结果]\n{text}",
                file_path=file_path,
                capability=HandlerCapability.OCR_TEXT,
                metadata=metadata,
            )

        except ImportError:
            self._logger.warning("pytesseract 未安装，无法进行 OCR 识别")
            return self._create_error_result("OCR 功能需要安装 pytesseract 和 tesseract-ocr", file_path)
        except Exception as e:
            self._logger.exception(f"OCR 识别失败")
            return self._create_error_result(f"OCR 识别失败: {str(e)}", file_path)

    def _get_mime_type(self, file_path: Path) -> str:
        ext = file_path.suffix.lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
            '.webp': 'image/webp',
            '.ico': 'image/x-icon',
            '.heic': 'image/heic',
            '.heif': 'image/heif',
            '.avif': 'image/avif',
            '.svg': 'image/svg+xml',
            '.psd': 'image/vnd.adobe.photoshop',
        }
        return mime_types.get(ext, 'application/octet-stream')

    def _extract_image_metadata(self, file_path: Path, raw_bytes: bytes | None = None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            'file_name': file_path.name,
            'file_size': file_path.stat().st_size,
            'format': file_path.suffix.lower().lstrip('.'),
        }

        try:
            with Image.open(file_path) as img:
                metadata['width'] = img.width
                metadata['height'] = img.height
                metadata['mode'] = img.mode
                metadata['format'] = img.format or file_path.suffix.lower().lstrip('.')

                if hasattr(img, 'info'):
                    metadata['dpi'] = img.info.get('dpi', 'N/A')
                    metadata['transparency'] = img.info.get('transparency', None)

                if img.mode in ('RGB', 'RGBA'):
                    metadata['has_transparency'] = img.mode == 'RGBA' or 'A' in img.getbands()

        except Exception as e:
            self._logger.warning(f"无法提取图片元数据: {e}")
            metadata['metadata_error'] = str(e)

        return metadata

    def get_base64_data(self, file_path: str | Path) -> str | None:
        result = self._read_as_base64(Path(file_path))
        if result.success and result.content:
            for line in result.content.split('\n'):
                if line.startswith('data:'):
                    return line
        return None

    def get_dimensions(self, file_path: str | Path) -> tuple[int, int] | None:
        try:
            with Image.open(file_path) as img:
                return (img.width, img.height)
        except Exception:
            return None

    def is_supported_format(self, file_path: str | Path) -> bool:
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions

    def validate_image(self, file_path: str | Path) -> tuple[bool, str]:
        try:
            with Image.open(file_path) as img:
                img.verify()
            return True, ""
        except Exception as e:
            return False, f"图片文件无效: {str(e)}"