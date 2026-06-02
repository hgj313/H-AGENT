"""Audio File Handler

Handler for audio files.
"""

from pathlib import Path

from .base_handler import BaseFileHandler, FileReadResult, HandlerCapability


class AudioFileHandler(BaseFileHandler):
    """Handler for audio files
    
    Supports: .mp3, .wav, .flac, .aac, .ogg, etc.
    """
    
    name = "audio"
    supported_extensions = {
        '.mp3', '.wav', '.flac', '.aac', '.ogg',
        '.m4a', '.wma', '.ape', '.alac',
    }
    
    def _read_impl(self, file_path: str) -> FileReadResult:
        """Read audio file (return metadata and transcription if available)
        
        Args:
            file_path: File path
            
        Returns:
            FileReadResult
        """
        metadata = self.get_metadata(file_path)
        
        return FileReadResult(
            success=True,
            content=f"[Audio file: {Path(file_path).name}]\n"
                    f"Duration: {metadata.get('duration', 'Unknown')}\n"
                    f"Size: {metadata.get('size', 0)} bytes",
            metadata=metadata
        )
    
    def _get_capabilities(self) -> set[HandlerCapability]:
        """Get handler capabilities"""
        return {
            HandlerCapability.READ_BINARY,
            HandlerCapability.SUPPORT_LARGE_FILE,
        }
    
    def get_audio_metadata(self, file_path: str) -> dict:
        """Get audio-specific metadata
        
        Args:
            file_path: File path
            
        Returns:
            Audio metadata dict
        """
        metadata = self.get_metadata(file_path)
        path = Path(file_path)
        
        metadata['format'] = path.suffix.lower()[1:]
        metadata['audio_type'] = 'audio'
        
        try:
            import struct
            if path.suffix.lower() == '.wav':
                with open(file_path, 'rb') as f:
                    header = f.read(44)
                    if header[:4] == b'RIFF':
                        channels = struct.unpack('<H', header[22:24])[0]
                        sample_rate = struct.unpack('<I', header[24:28])[0]
                        metadata['channels'] = channels
                        metadata['sample_rate'] = sample_rate
        except Exception:
            pass
        
        return metadata