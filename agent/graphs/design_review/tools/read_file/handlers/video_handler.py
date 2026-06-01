"""视频文件处理器。

支持各种视频格式的读取，提供元数据提取和帧提取能力。
用于多模态模型处理视频内容。
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from .base_handler import (
    BaseFileHandler,
    FileReadResult,
    HandlerCapability,
)

logger = logging.getLogger(__name__)


class VideoFileHandler(BaseFileHandler):
    name: str = "VideoFileHandler"
    supported_extensions: set[str] = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
        '.m4v', '.mpg', '.mpeg', '.3gp', '.ogv', '.ts', '.mts',
        '.av1', '.vp8', '.vp9',
    }

    def __init__(self, max_file_size: int | None = None, enable_frames: bool = False) -> None:
        super().__init__(max_file_size)
        self._enable_frames = enable_frames

    def get_capabilities(self) -> set[HandlerCapability]:
        capabilities = {HandlerCapability.METADATA, HandlerCapability.VIDEO_DESCRIPTION}
        if self._enable_frames:
            capabilities.add(HandlerCapability.BASE64_ENCODED)
        return capabilities

    def _do_read(self, file_path: Path, **kwargs: Any) -> FileReadResult:
        metadata = self._extract_video_metadata(file_path)

        extract_frames = kwargs.get('extract_frames', False)
        if extract_frames and self._enable_frames:
            return self._extract_video_frames(file_path, metadata, kwargs)
        else:
            content = self._format_metadata_as_text(metadata)
            return self._create_success_result(
                content=content,
                file_path=file_path,
                capability=HandlerCapability.METADATA,
                metadata=metadata,
            )

    def _extract_video_metadata(self, file_path: Path) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            'file_name': file_path.name,
            'file_size': file_path.stat().st_size,
            'format': file_path.suffix.lower().lstrip('.'),
        }

        try:
            from ffprobe import FFProbe

            probe = FFProbe(str(file_path))

            for stream in probe.streams:
                if stream.is_video():
                    metadata['duration'] = probe.duration
                    metadata['width'] = stream.width()
                    metadata['height'] = stream.height()
                    metadata['fps'] = stream.average_frame_rate()
                    metadata['codec'] = stream.codec_name()
                    metadata['bitrate'] = probe.bit_rate
                    break

            video_streams = [s for s in probe.streams if s.is_video()]
            audio_streams = [s for s in probe.streams if s.is_audio()]

            metadata['video_streams'] = len(video_streams)
            metadata['audio_streams'] = len(audio_streams)

        except ImportError:
            self._logger.debug("ffprobe 未安装，尝试使用 cv2")
            try:
                import cv2

                cap = cv2.VideoCapture(str(file_path))
                if cap.isOpened():
                    metadata['width'] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    metadata['height'] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    metadata['fps'] = cap.get(cv2.CAP_PROP_FPS)
                    metadata['frame_count'] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    metadata['duration'] = metadata['frame_count'] / metadata['fps'] if metadata.get('fps') else 0
                    cap.release()
            except ImportError:
                self._logger.debug("cv2 未安装，无法提取详细视频元数据")
            except Exception as e:
                self._logger.warning(f"使用 cv2 提取视频元数据失败: {e}")
        except Exception as e:
            self._logger.warning(f"提取视频元数据失败: {e}")
            metadata['metadata_error'] = str(e)

        return metadata

    def _format_metadata_as_text(self, metadata: dict[str, Any]) -> str:
        lines = [
            f"[视频文件: {metadata.get('file_name', 'unknown')}]",
            f"[格式: {metadata.get('format', 'unknown')}]",
            f"[大小: {metadata.get('file_size', 0) / 1024 / 1024:.2f} MB]",
        ]

        if metadata.get('duration'):
            minutes = int(metadata['duration'] // 60)
            seconds = int(metadata['duration'] % 60)
            lines.append(f"[时长: {minutes}分{seconds}秒]")

        if metadata.get('width') and metadata.get('height'):
            lines.append(f"[分辨率: {metadata['width']}x{metadata['height']}]")

        if metadata.get('fps'):
            lines.append(f"[帧率: {metadata['fps']:.2f} fps]")

        if metadata.get('codec'):
            lines.append(f"[编码: {metadata['codec']}]")

        if metadata.get('bitrate'):
            lines.append(f"[比特率: {metadata['bitrate'] / 1000:.0f} kbps]")

        if metadata.get('video_streams'):
            lines.append(f"[视频流: {metadata['video_streams']}]")

        if metadata.get('audio_streams'):
            lines.append(f"[音频流: {metadata['audio_streams']}]")

        return "\n".join(lines)

    def _extract_video_frames(
        self,
        file_path: Path,
        metadata: dict[str, Any],
        kwargs: Any,
    ) -> FileReadResult:
        if not self._enable_frames:
            return self._create_error_result("帧提取功能未启用", file_path)

        try:
            import cv2

            cap = cv2.VideoCapture(str(file_path))
            if not cap.isOpened():
                cap.release()
                return self._create_error_result("无法打开视频文件", file_path)

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0

            frame_interval = kwargs.get('frame_interval', 1)
            max_frames = kwargs.get('max_frames', 10)

            frames_data: list[dict[str, Any]] = []
            frame_count = 0
            extracted = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_count % frame_interval == 0:
                    _, buffer = cv2.imencode('.jpg', frame)
                    base64_frame = base64.b64encode(buffer).decode('ascii')

                    timestamp = frame_count / fps if fps > 0 else 0
                    frames_data.append({
                        'frame_number': frame_count,
                        'timestamp': timestamp,
                        'base64': base64_frame[:100] + '...',
                        'base64_length': len(base64_frame),
                    })

                    extracted += 1
                    if extracted >= max_frames:
                        break

                frame_count += 1

            cap.release()

            result_metadata = {
                **metadata,
                'frames_extracted': extracted,
                'total_frames': total_frames,
                'duration': duration,
            }

            content_parts = [
                f"[视频帧提取结果]",
                f"[总帧数: {total_frames}, 提取帧数: {extracted}]",
                f"[时长: {duration:.2f}秒, 帧率: {fps:.2f}fps]",
                "",
            ]

            for fd in frames_data:
                content_parts.append(
                    f"[帧 {fd['frame_number']}] 时间戳: {fd['timestamp']:.2f}秒, "
                    f"Base64长度: {fd['base64_length']}字符"
                )

            return self._create_success_result(
                content="\n".join(content_parts),
                file_path=file_path,
                capability=HandlerCapability.BASE64_ENCODED,
                metadata=result_metadata,
            )

        except ImportError:
            return self._create_error_result("帧提取需要安装 opencv-python", file_path)
        except Exception as e:
            self._logger.exception(f"视频帧提取失败")
            return self._create_error_result(f"视频帧提取失败: {str(e)}", file_path)

    def get_duration(self, file_path: str | Path) -> float | None:
        try:
            from ffprobe import FFProbe

            probe = FFProbe(str(file_path))
            return probe.duration
        except Exception:
            try:
                import cv2

                cap = cv2.VideoCapture(str(file_path))
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    cap.release()
                    return frame_count / fps if fps > 0 else None
            except Exception:
                return None
        return None

    def validate_video(self, file_path: str | Path) -> tuple[bool, str]:
        try:
            import cv2

            cap = cv2.VideoCapture(str(file_path))
            if not cap.isOpened():
                cap.release()
                return False, "无法打开视频文件"
            cap.release()
            return True, ""
        except Exception as e:
            return False, f"视频文件无效: {str(e)}"