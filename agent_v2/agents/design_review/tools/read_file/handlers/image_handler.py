"""Image File Handler

Handler for image files.
"""

import base64
from pathlib import Path

from .base_handler import BaseFileHandler, FileReadResult, HandlerCapability


class ImageFileHandler(BaseFileHandler):
    """Handler for image files
    
    Supports: .jpg, .jpeg, .png, .gif, .webp, .bmp, etc.
    """
    
    name = "image"
    supported_extensions = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp',
        '.bmp', '.ico', '.tiff', '.tif', '.svg',
        '.heic', '.heif', '.avif',
    }
    
    def __init__(self, encoding: str = 'utf-8'):
        """Initialize image handler
        
        Args:
            encoding: Encoding for base64 conversion
        """
        super().__init__()
        self.encoding = encoding
    
    def _read_impl(self, file_path: str) -> FileReadResult:
        """Read image file as base64
        
        Args:
            file_path: File path
            
        Returns:
            FileReadResult with base64 content
        """
        try:
            path = Path(file_path)
            
            with open(path, 'rb') as f:
                image_data = f.read()
            
            encoded = base64.b64encode(image_data).decode(self.encoding)
            
            mime_type = self._get_mime_type(path.suffix)
            base64_content = f"data:{mime_type};base64,{encoded}"
            
            return FileReadResult(
                success=True,
                content=base64_content,
                metadata=self.get_metadata(file_path)
            )
        except Exception as e:
            return FileReadResult(
                success=False,
                content="",
                error=f"读取图片失败: {str(e)}"
            )
    
    def _get_capabilities(self) -> set[HandlerCapability]:
        """Get handler capabilities"""
        return {
            HandlerCapability.READ_BINARY,
            HandlerCapability.SUPPORT_LARGE_FILE,
        }
    
    def _get_mime_type(self, extension: str) -> str:
        """Get MIME type for image"""
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
            '.ico': 'image/x-icon',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
            '.svg': 'image/svg+xml',
        }
        return mime_types.get(extension.lower(), 'image/jpeg')
    
    def read_as_binary(self, file_path: str) -> FileReadResult:
        """Read image as binary data
        
        Args:
            file_path: File path
            
        Returns:
            FileReadResult with binary content
        """
        try:
            path = Path(file_path)
            
            with open(path, 'rb') as f:
                content = f.read()
            
            return FileReadResult(
                success=True,
                content=content,
                metadata=self.get_metadata(file_path)
            )
        except Exception as e:
            return FileReadResult(
                success=False,
                content="",
                error=f"读取图片失败: {str(e)}"
            )