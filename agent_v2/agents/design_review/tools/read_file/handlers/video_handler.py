"""Video File Handler

Handler for video files.
"""

from pathlib import Path

from .base_handler import BaseFileHandler, FileReadResult, HandlerCapability


class VideoFileHandler(BaseFileHandler):
    """Handler for video files
    
    Supports: .mp4, .avi, .mkv, .mov, .wmv, etc.
    """
    
    name = "video"
    supported_extensions = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv',
        '.flv', '.webm', '.m4v', '.mpg', '.mpeg',
    }
    
    def _read_impl(self, file_path: str) -> FileReadResult:
        """Read video file (return metadata)
        
        Args:
            file_path: File path
            
        Returns:
            FileReadResult
        """
        metadata = self.get_metadata(file_path)
        
        return FileReadResult(
            success=True,
            content=f"[Video file: {Path(file_path).name}]\n"
                    f"Size: {metadata.get('size', 0) / (1024*1024):.2f} MB\n"
                    f"Format: {Path(file_path).suffix}",
            metadata=metadata
        )
    
    def _get_capabilities(self) -> set[HandlerCapability]:
        """Get handler capabilities"""
        return {
            HandlerCapability.READ_BINARY,
            HandlerCapability.SUPPORT_LARGE_FILE,
        }
    
    def get_video_metadata(self, file_path: str) -> dict:
        """Get video-specific metadata
        
        Args:
            file_path: File path
            
        Returns:
            Video metadata dict
        """
        metadata = self.get_metadata(file_path)
        path = Path(file_path)
        
        metadata['format'] = path.suffix.lower()[1:]
        metadata['video_type'] = 'video'
        metadata['size_mb'] = metadata.get('size', 0) / (1024 * 1024)
        
        return metadata