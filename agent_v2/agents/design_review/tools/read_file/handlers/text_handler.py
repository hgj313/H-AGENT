"""Text File Handler

Handler for text-based files.
"""

from pathlib import Path
from typing import Optional, List

from .base_handler import BaseFileHandler, FileReadResult, HandlerCapability


class TextFileHandler(BaseFileHandler):
    """Handler for text files
    
    Supports: .txt, .md, .json, .yaml, .py, .js, etc.
    """
    
    name = "text"
    supported_extensions = {
        '.txt', '.md', '.markdown',
        '.json', '.yaml', '.yml', '.toml',
        '.py', '.js', '.ts', '.jsx', '.tsx',
        '.java', '.c', '.cpp', '.h', '.hpp',
        '.cs', '.go', '.rs', '.rb', '.php',
        '.html', '.htm', '.css', '.scss', '.sass', '.less',
        '.xml', '.sql', '.sh', '.bash', '.zsh',
        '.properties', '.env', '.gitignore', '.dockerfile',
        '.log', '.csv', '.tsv', '.ini', '.cfg',
    }
    
    def __init__(self, max_size: int = 10 * 1024 * 1024):
        """Initialize text handler
        
        Args:
            max_size: Maximum file size in bytes (default 10MB)
        """
        super().__init__()
        self.max_size = max_size
    
    def _read_impl(self, file_path: str) -> FileReadResult:
        """Read text file
        
        Args:
            file_path: File path
            
        Returns:
            FileReadResult
        """
        try:
            path = Path(file_path)
            
            if path.stat().st_size > self.max_size:
                return FileReadResult(
                    success=False,
                    content="",
                    error=f"文件过大: {path.stat().st_size / (1024*1024):.2f}MB (最大 {self.max_size / (1024*1024):.0f}MB)"
                )
            
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            return FileReadResult(
                success=True,
                content=content,
                metadata=self.get_metadata(file_path)
            )
        except UnicodeDecodeError:
            return self._read_with_fallback_encoding(file_path)
        except Exception as e:
            return FileReadResult(
                success=False,
                content="",
                error=f"读取文件失败: {str(e)}"
            )
    
    def _read_with_fallback_encoding(self, file_path: str) -> FileReadResult:
        """Try reading with fallback encodings
        
        Args:
            file_path: File path
            
        Returns:
            FileReadResult
        """
        encodings = ['gbk', 'gb2312', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                path = Path(file_path)
                with open(path, 'r', encoding=encoding, errors='replace') as f:
                    content = f.read()
                
                return FileReadResult(
                    success=True,
                    content=content,
                    metadata=self.get_metadata(file_path)
                )
            except Exception:
                continue
        
        return FileReadResult(
            success=False,
            content="",
            error="无法使用任何编码读取文件"
        )
    
    def _get_capabilities(self) -> set[HandlerCapability]:
        """Get handler capabilities"""
        return {
            HandlerCapability.READ_TEXT,
            HandlerCapability.READ_STREAMING,
        }
    
    def read_lines(
        self,
        file_path: str,
        start_line: int = 0,
        max_lines: Optional[int] = None
    ) -> FileReadResult:
        """Read file lines with range
        
        Args:
            file_path: File path
            start_line: Starting line number (0-indexed)
            max_lines: Maximum number of lines
            
        Returns:
            FileReadResult with lines
        """
        try:
            path = Path(file_path)
            
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            
            if start_line >= len(lines):
                return FileReadResult(
                    success=True,
                    content="",
                    metadata={"total_lines": len(lines)}
                )
            
            end_line = len(lines) if max_lines is None else min(start_line + max_lines, len(lines))
            content = ''.join(lines[start_line:end_line])
            
            return FileReadResult(
                success=True,
                content=content,
                metadata={
                    "total_lines": len(lines),
                    "start_line": start_line,
                    "end_line": end_line,
                    "lines_read": end_line - start_line
                }
            )
        except Exception as e:
            return FileReadResult(
                success=False,
                content="",
                error=f"读取行失败: {str(e)}"
            )