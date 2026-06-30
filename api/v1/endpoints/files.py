"""
文件上传端点。
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse

from api.v1.schemas.files import (
    FileUploadResponse,
    FileInfo,
    FileValidationError,
    FileType,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    UploadProgress,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 上传目录
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def _detect_file_type(filename: str) -> FileType:
    """根据扩展名检测文件类型。"""
    ext = Path(filename).suffix.lower()
    for file_type, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return file_type
    return FileType.OTHER


def _validate_file(file: UploadFile) -> tuple[bool, str | None]:
    """
    验证文件。

    Returns:
        (is_valid, error_message)
    """
    if not file.filename:
        return False, "文件名为空"

    # 检查文件类型
    file_type = _detect_file_type(file.filename)
    if file_type == FileType.OTHER:
        allowed = []
        for ft, exts in ALLOWED_EXTENSIONS.items():
            allowed.extend(exts)
        return False, f"不支持的文件类型，允许的类型: {', '.join(allowed)}"

    return True, None


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    description: str = Form(None),
) -> FileUploadResponse:
    """
    上传单个文件。

    支持的文件类型：
    - 文档: pdf, doc, docx, md, txt, rtf
    - 图片: jpg, jpeg, png, gif, webp, bmp
    - 表格: xls, xlsx, csv
    - 压缩包: zip, rar, 7z

    最大文件大小: 50MB
    """
    # 验证文件
    is_valid, error_msg = _validate_file(file)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 读取文件内容并检查大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制，最大允许 {MAX_FILE_SIZE // (1024*1024)}MB",
        )

    # 生成文件ID和路径
    file_id = f"file-{uuid.uuid4().hex[:12]}"
    file_type = _detect_file_type(file.filename)
    ext = Path(file.filename).suffix
    saved_filename = f"{file_id}{ext}"
    file_path = UPLOAD_DIR / file_type.value / saved_filename

    # 创建目录
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # 保存文件
    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(f"文件已上传: {file.filename} -> {file_path}")

    return FileUploadResponse(
        file_id=file_id,
        filename=file.filename,
        file_type=file_type,
        file_size=len(content),
        upload_time=datetime.now(),
        file_path=str(file_path),
        url=f"/api/v1/files/{file_id}",
    )


@router.post("/upload/progress/{file_id}")
async def upload_with_progress(
    file_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> StreamingResponse:
    """
    带进度的文件上传（SSE 流式返回进度）。
    """
    async def progress_stream():
        try:
            # 验证文件
            is_valid, error_msg = _validate_file(file)
            if not is_valid:
                yield UploadProgress(
                    file_id=file_id,
                    filename=file.filename or "unknown",
                    progress=0,
                    status="error",
                    error=error_msg,
                ).model_dump_json() + "\n"
                return

            # 模拟进度（实际应该分块读取）
            yield UploadProgress(
                file_id=file_id,
                filename=file.filename or "unknown",
                progress=0.1,
                status="uploading",
            ).model_dump_json() + "\n"

            # 读取文件
            content = await file.read()
            total_size = len(content)

            yield UploadProgress(
                file_id=file_id,
                filename=file.filename or "unknown",
                progress=0.5,
                status="processing",
            ).model_dump_json() + "\n"

            # 检查大小
            if total_size > MAX_FILE_SIZE:
                yield UploadProgress(
                    file_id=file_id,
                    filename=file.filename or "unknown",
                    progress=0.5,
                    status="error",
                    error=f"文件大小超过限制",
                ).model_dump_json() + "\n"
                return

            # 保存文件
            file_type = _detect_file_type(file.filename)
            ext = Path(file.filename).suffix
            saved_filename = f"{file_id}{ext}"
            file_path = UPLOAD_DIR / file_type.value / saved_filename
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "wb") as f:
                f.write(content)

            # 完成
            yield UploadProgress(
                file_id=file_id,
                filename=file.filename or "unknown",
                progress=1.0,
                status="completed",
            ).model_dump_json() + "\n"

        except Exception as e:
            logger.error(f"Upload error: {e}", exc_info=True)
            yield UploadProgress(
                file_id=file_id,
                filename=file.filename or "unknown",
                progress=0,
                status="error",
                error=str(e),
            ).model_dump_json() + "\n"

    return StreamingResponse(
        progress_stream(),
        media_type="text/event-stream",
    )


@router.get("/{file_id}", response_model=FileInfo)
async def get_file_info(file_id: str) -> FileInfo:
    """获取文件信息。"""
    # 搜索文件
    for file_type_dir in UPLOAD_DIR.iterdir():
        if file_type_dir.is_dir():
            for file_path in file_type_dir.iterdir():
                if file_path.stem == file_id:
                    stat = file_path.stat()
                    return FileInfo(
                        file_id=file_id,
                        filename=file_path.name,
                        file_type=FileType(file_type_dir.name),
                        file_size=stat.st_size,
                        upload_time=datetime.fromtimestamp(stat.st_mtime),
                        file_path=str(file_path),
                    )

    raise HTTPException(status_code=404, detail=f"文件未找到: {file_id}")


@router.get("/{file_id}/raw")
async def get_file_raw(file_id: str) -> StreamingResponse:
    """获取文件原始字节流（供视觉模型 / 浏览器 fetch 直接消费）。

    设计要点：
      - 视觉模型（如 qwen-vl）需要 fetch 公网 URL 拿到图片二进制
      - 前端 <img src> 也直接用这个 URL
      - 必须返回正确的 Content-Type，否则视觉模型会拒绝

    安全：
      - file_id 只能含 [a-zA-Z0-9_-]（防路径遍历）
      - 必须找到真实存在的文件才返回（不构造路径，避免越界）
    """
    import re as _re
    if not _re.fullmatch(r"file-[a-zA-Z0-9_]+", file_id):
        raise HTTPException(status_code=400, detail=f"非法 file_id: {file_id!r}")

    # 在 UPLOAD_DIR 下扫所有子目录找匹配 file_id 的文件
    # （兼容 files.py 直传 + LocalStorageBackend 上传 两种存储位置）
    matched: Path | None = None
    if UPLOAD_DIR.is_dir():
        for child in UPLOAD_DIR.iterdir():
            if not child.is_dir():
                continue
            for cand in child.iterdir():
                if cand.is_file() and cand.stem == file_id:
                    matched = cand
                    break
            if matched:
                break
    if matched is None:
        raise HTTPException(status_code=404, detail=f"文件未找到: {file_id}")

    # Content-Type：先按扩展名查 mime，失败则 octet-stream
    import mimetypes as _mimetypes
    mime, _ = _mimetypes.guess_type(matched.name)
    if not mime:
        mime = "application/octet-stream"

    def _iter():
        with open(matched, "rb") as f:  # type: ignore[arg-type]
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type=mime,
        headers={
            "Content-Length": str(matched.stat().st_size),  # type: ignore[arg-type]
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.delete("/{file_id}")
async def delete_file(file_id: str) -> dict[str, str]:
    """删除文件。"""
    for file_type_dir in UPLOAD_DIR.iterdir():
        if file_type_dir.is_dir():
            for file_path in file_type_dir.iterdir():
                if file_path.stem == file_id:
                    file_path.unlink()
                    logger.info(f"文件已删除: {file_path}")
                    return {"status": "deleted", "file_id": file_id}

    raise HTTPException(status_code=404, detail=f"文件未找到: {file_id}")
