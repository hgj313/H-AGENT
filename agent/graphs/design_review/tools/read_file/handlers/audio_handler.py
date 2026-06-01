"""音频文件处理器。

支持各种音频格式的读取，提供元数据提取和转录能力。
用于多模态模型处理音频内容。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base_handler import (
    BaseFileHandler,
    FileReadResult,
    HandlerCapability,
)

logger = logging.getLogger(__name__)


class AudioFileHandler(BaseFileHandler):
    name: str = "AudioFileHandler"
    supported_extensions: set[str] = {
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a',
        '.opus', '.ape', '.alac', '.aiff', '.aac', '.pcm',
    }

    def __init__(self, max_file_size: int | None = None, enable_transcription: bool = False) -> None:
        super().__init__(max_file_size)
        self._enable_transcription = enable_transcription

    def get_capabilities(self) -> set[HandlerCapability]:
        capabilities = {HandlerCapability.METADATA}
        if self._enable_transcription:
            capabilities.add(HandlerCapability.AUDIO_TRANSCRIPTION)
        return capabilities

    def _do_read(self, file_path: Path, **kwargs: Any) -> FileReadResult:
        metadata = self._extract_audio_metadata(file_path)

        if self._enable_transcription and kwargs.get('transcribe', False):
            return self._transcribe_audio(file_path, metadata)
        else:
            content = self._format_metadata_as_text(metadata)
            return self._create_success_result(
                content=content,
                file_path=file_path,
                capability=HandlerCapability.METADATA,
                metadata=metadata,
            )

    def _extract_audio_metadata(self, file_path: Path) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            'file_name': file_path.name,
            'file_size': file_path.stat().st_size,
            'format': file_path.suffix.lower().lstrip('.'),
        }

        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(str(file_path))
            if audio is not None:
                metadata['duration'] = getattr(audio.info, 'length', None)
                metadata['bitrate'] = getattr(audio.info, 'bitrate', None)
                metadata['sample_rate'] = getattr(audio.info, 'sample_rate', None)
                metadata['channels'] = getattr(audio.info, 'channels', None)

                if audio.tags:
                    metadata['title'] = getattr(audio.tags, 'title', None)
                    metadata['artist'] = getattr(audio.tags, 'artist', None)
                    metadata['album'] = getattr(audio.tags, 'album', None)
                    metadata['year'] = getattr(audio.tags, 'date', None)

        except ImportError:
            self._logger.debug("mutagen 未安装，无法提取详细音频元数据")
        except Exception as e:
            self._logger.warning(f"提取音频元数据失败: {e}")
            metadata['metadata_error'] = str(e)

        return metadata

    def _format_metadata_as_text(self, metadata: dict[str, Any]) -> str:
        lines = [
            f"[音频文件: {metadata.get('file_name', 'unknown')}]",
            f"[格式: {metadata.get('format', 'unknown')}]",
            f"[大小: {metadata.get('file_size', 0) / 1024:.2f} KB]",
        ]

        if metadata.get('duration'):
            minutes = int(metadata['duration'] // 60)
            seconds = int(metadata['duration'] % 60)
            lines.append(f"[时长: {minutes}分{seconds}秒]")

        if metadata.get('bitrate'):
            lines.append(f"[比特率: {metadata['bitrate'] / 1000:.0f} kbps]")

        if metadata.get('sample_rate'):
            lines.append(f"[采样率: {metadata['sample_rate']} Hz]")

        if metadata.get('title'):
            lines.append(f"[标题: {metadata['title']}]")

        if metadata.get('artist'):
            lines.append(f"[艺术家: {metadata['artist']}]")

        if metadata.get('album'):
            lines.append(f"[专辑: {metadata['album']}]")

        return "\n".join(lines)

    def _transcribe_audio(self, file_path: Path, metadata: dict[str, Any]) -> FileReadResult:
        if not self._enable_transcription:
            return self._create_error_result("转录功能未启用", file_path)

        try:
            import whisper

            model = whisper.load_model(kwargs.get('whisper_model', 'base'))
            result = model.transcribe(str(file_path), language=kwargs.get('language', None))

            transcription_metadata = {
                **metadata,
                'language': result.get('language'),
                'transcription_length': len(result.get('text', '')),
            }

            content = f"[音频转录结果]\n语言: {result.get('language', 'unknown')}\n\n{result.get('text', '')}"

            return self._create_success_result(
                content=content,
                file_path=file_path,
                capability=HandlerCapability.AUDIO_TRANSCRIPTION,
                metadata=transcription_metadata,
            )

        except ImportError:
            return self._create_error_result("音频转录需要安装 openai-whisper", file_path)
        except Exception as e:
            self._logger.exception(f"音频转录失败")
            return self._create_error_result(f"音频转录失败: {str(e)}", file_path)

    def get_duration(self, file_path: str | Path) -> float | None:
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(str(file_path))
            if audio and hasattr(audio.info, 'length'):
                return audio.info.length
        except Exception:
            return None
        return None

    def validate_audio(self, file_path: str | Path) -> tuple[bool, str]:
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(str(file_path))
            if audio is None:
                return False, "文件无法被识别为音频文件"
            return True, ""
        except Exception as e:
            return False, f"音频文件无效: {str(e)}"