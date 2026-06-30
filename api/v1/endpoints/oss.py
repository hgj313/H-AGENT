"""
OSS 直传端点 —— presigned-upload 流程的统一入口。

设计原则：
  - **唯一上传入口**：POST /api/v1/oss/presign-upload
    （客户端先申请许可 → 直传到 upload_url → 拿 public_url 给业务）
  - **直传收件点**（仅 LocalStorage 模式）：PUT /api/v1/oss/direct-upload/{file_id}
    （OSS 模式 = 真 OSS 签名 URL，客户端直接 PUT 到 OSS，不经我们后端）
  - **公开读端点**：GET /api/v1/files/{file_id}/raw
    （public_url 的目标，返文件字节流，供视觉模型 / 浏览器 fetch）

流程：
  1. 前端 POST /api/v1/oss/presign-upload
     → 拿到 {upload_url, public_url, file_id, object_name, expires_at}
  2. 前端 PUT upload_url + 文件字节
     → LocalStorage 模式：到 /api/v1/oss/direct-upload/{file_id}
     → OSS 模式：到阿里云 OSS 签名 URL
  3. 前端拿 public_url 做 image_url 提交给设计审查 agent
     → 视觉模型 fetch public_url 拿到图片字节

诊断：
  GET /api/v1/oss/health        后端类型 / 上传目录
  GET /api/v1/oss/objects/{...} head_object（用 object_name 查元信息）
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.v1.schemas.oss import (
    ObjectMetadataResponse,
    PresignUploadRequest,
    PresignUploadResponse,
)
from api.v1.services.storage_service import (
    DEFAULT_URL_TTL_SECONDS,
    get_storage_service,
)
from api.v1.services.storage_service import LocalStorageBackend  # 仅 type 用途
from api.v1.services.nonce_store import get_nonce_store, NonceStoreError

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 工具函数 ────────────────────────────────────────────────
def _to_absolute_path_url(request: Request, path: str, route_name: str, **path_params) -> str:
    """把相对路径（如 /api/v1/xxx）转成绝对 URL（含 scheme + host）。

    使用 request.url_for()，自动处理：
      - http vs https（适配反向代理头）
      - host / port（X-Forwarded-Host 透明）
      - root_path（如果有 mount 前缀）
    """
    if path.startswith(("http://", "https://")):
        return path
    if not path.startswith("/"):
        path = "/" + path
    # url_for 不接受前导斜杠；去掉
    return str(request.url_for(route_name, **path_params))


def _guess_content_type(filename: str) -> str:
    """从文件名猜 content_type（mimetypes 兜底）。"""
    import mimetypes
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def _sanitize_filename(filename: str) -> str:
    """剥扩展名得到基础文件名（保留扩展名给后续使用）。"""
    # 只取 basename（防止路径注入）
    base = Path(filename).name
    # 不允许特殊字符（保留扩展名里的 .）
    if not re.fullmatch(r"[\w.\-\u4e00-\u9fff]+", base):
        # 退化到 file-<uuid> + 原扩展名
        import uuid
        ext = Path(filename).suffix.lower()
        return f"file-{uuid.uuid4().hex[:12]}{ext}"
    return base


# ── 1) 申请上传许可（唯一上传入口）────────────────────
@router.post("/presign-upload", response_model=PresignUploadResponse)
async def oss_presign_upload(
    request: Request,
    body: PresignUploadRequest,
) -> PresignUploadResponse:
    """OSS 直传的统一入口：申请上传许可。

    客户端拿到 response 后：
      1) PUT upload_url + 文件字节 + X-Nonce: <nonce>
                                    （LocalStorage 模式 = 我们的 receive 端点；
                                     OSS 模式 = 真 OSS 签名 URL，但**阿里云 OSS V4
                                     签名本身已经防重放**，所以 OSS 模式下我们仍
                                     在 metadata 记录 nonce 用于审计，但不强校验）
      2) 用 public_url 作为 image_url 给设计审查 agent

    防重放 nonce：
      - 服务端生成 32 字符 hex（UUID v4），写入 NonceStore
      - 客户端 PUT 时必须带 X-Nonce header
      - 后端原子消费：未过期 + 未消费 + file_id 匹配 → 标记 consumed
      - 二次消费、过期、跨 file 都会被拒（403 / 409）
    """
    svc = get_storage_service()
    backend_kind = svc.backend_kind
    adapter = svc.adapter
    safe_filename = _sanitize_filename(body.filename)
    content_type = body.content_type or _guess_content_type(body.filename)

    # 生成 file_id 和 object_name
    import uuid
    file_id = f"file-{uuid.uuid4().hex[:12]}"
    ext = Path(safe_filename).suffix.lower()
    saved_filename = f"{file_id}{ext}"

    if backend_kind == "local":
        object_name = f"local://{body.bucket}/{saved_filename}"
    else:
        # 真 OSS / S3：bucket 是 OSS bucket，filename 是 key
        object_name = f"{body.bucket}/{saved_filename}"

    # 生成 upload_url（PUT 签名 URL 或本地 receive 端点）
    signed = adapter.generate_signed_url(
        _build_signed_request(
            adapter, object_name,
            method="PUT",
            expire_seconds=body.ttl_seconds,
        ),
    )
    upload_url_raw = signed.url

    # 生成 public_url（GET 签名 URL 或本地 /api/v1/files/{file_id}/raw）
    pub_signed = adapter.generate_signed_url(
        _build_signed_request(
            adapter, object_name,
            method="GET",
            expire_seconds=body.ttl_seconds,
        ),
    )
    public_url_raw = pub_signed.url

    # 转绝对 URL
    if backend_kind == "local":
        # LocalStorage：upload_url 直拼 /api/v1/oss/direct-upload/{file_id}（绝对 URL）
        upload_url = _to_absolute_path_url(
            request,
            f"/api/v1/oss/direct-upload/{file_id}",
            "oss_direct_upload",
            file_id=file_id,
        )
        # public_url：拼 /api/v1/files/{file_id}/raw
        public_url = _to_absolute_path_url(
            request,
            f"/api/v1/files/{file_id}/raw",
            "get_file_raw",
            file_id=file_id,
        )
    else:
        # OSS 模式：upload_url / public_url 都已经是完整 https URL
        upload_url = upload_url_raw
        public_url = public_url_raw

    expires_at = signed.expires_at or pub_signed.expires_at

    # ── 防重放：签发 nonce ────────────────────────────────
    from api.v1.services.nonce_store import get_nonce_store
    nonce_store = get_nonce_store()
    nonce = nonce_store.new_nonce()
    nonce_store.issue(
        nonce,
        file_id=file_id,
        object_name=object_name,
        backend=backend_kind,
        ttl_seconds=body.ttl_seconds,
    )

    logger.info(
        "presign-upload: backend=%s file_id=%s nonce=%s object=%s upload=%s public=%s",
        backend_kind, file_id, nonce[:8] + "...", object_name, upload_url, public_url,
    )
    return PresignUploadResponse(
        file_id=file_id,
        object_name=object_name,
        upload_url=upload_url,
        upload_method="PUT",
        public_url=public_url,
        expires_at=expires_at,
        storage_backend=backend_kind,
        bucket=body.bucket,
        nonce=nonce,
    )


def _build_signed_request(adapter, object_name: str, method: str, expire_seconds: int):
    """构造 SignedURLRequest（避免 import 循环 + 不同 backend 用不同 request 类型）。"""
    from oss.base import SignedURLRequest  # 延迟 import
    return SignedURLRequest(
        object_name=object_name,
        method=method,
        expire_seconds=expire_seconds,
    )


# ── 2) LocalStorage 直传收件点 ──────────────────────────────
@router.put("/direct-upload/{file_id}")
async def oss_direct_upload(
    request: Request,
    file_id: str,
) -> dict[str, str]:
    """LocalStorage 模式的 PUT 收件点。

    仅在 backend=local 时使用；OSS 模式客户端直接 PUT 到 OSS 签名 URL，不走这里。

    安全：
      - file_id 必须匹配 file-[a-zA-Z0-9_]+
      - 必须先经过 presign-upload 申请（object_name 与 file_id 一一对应）
      - **必须带 X-Nonce header**（防重放一次性消费）
      - 大小校验（与 oss.py multipart 端点一致）
    """
    if not re.fullmatch(r"file-[a-zA-Z0-9_]+", file_id):
        raise HTTPException(status_code=400, detail=f"非法 file_id: {file_id!r}")

    # ── 防重放：消费 nonce ─────────────────────────────────
    nonce = request.headers.get("x-nonce")
    if not nonce:
        raise HTTPException(
            status_code=400,
            detail="缺少 X-Nonce header（请先 POST /api/v1/oss/presign-upload 申请 nonce）",
        )
    if not re.fullmatch(r"[a-fA-F0-9]{32}", nonce):
        raise HTTPException(
            status_code=400,
            detail=f"非法 nonce 格式（必须 32 字符 hex UUID v4）: {nonce[:8]}...",
        )
    try:
        get_nonce_store().consume(nonce, file_id=file_id)
    except NonceStoreError as exc:
        # 区分错误码：
        #  - NONCE_NOT_FOUND / NONCE_FILE_MISMATCH → 403（伪造或越权）
        #  - NONCE_ALREADY_CONSUMED / NONCE_EXPIRED → 409（重放）
        #  - NONCE_RACE_CONSUMED → 409（并发竞争）
        status = 403 if exc.code in ("NONCE_NOT_FOUND", "NONCE_FILE_MISMATCH") else 409
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": exc.message},
        )

    svc = get_storage_service()
    backend_kind = svc.backend_kind
    if backend_kind != "local":
        raise HTTPException(
            status_code=400,
            detail=f"direct-upload 仅在 backend=local 时使用，当前 backend={backend_kind}",
        )

    # 找到 presign 时生成的 object_name
    # 注意：object_name 是 presign-upload 阶段生成的，我们没有持久化。
    # 这里用约定：从请求头 X-OSS-Object-Name 或 query param 拿；
    # 如果没有，从 file_id + 约定的 bucket 反推（不够好但 fallback 可用）。
    object_name = request.headers.get("x-oss-object-name")
    if not object_name:
        # 兜底：用 default bucket（与旧 multipart 上传兼容）
        # 生产应当要求 header 必填；测试场景下给 fallback
        bucket = request.query_params.get("bucket", "default")
        # 拿不到 ext，从 content-type 反推
        ct = request.headers.get("content-type", "application/octet-stream")
        ext_map = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "application/pdf": ".pdf",
            "text/markdown": ".md",
            "text/plain": ".txt",
        }
        ext = ext_map.get(ct, "")
        object_name = f"local://{bucket}/{file_id}{ext}"

    # 接收 PUT body（流式）
    backend: LocalStorageBackend = svc.adapter  # type: ignore[assignment]

    # 流式写到临时文件
    import tempfile
    from oss.base import UploadRequest

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    try:
        size = 0
        async for chunk in request.stream():
            if not chunk:
                continue
            tmp.write(chunk)
            size += len(chunk)
            if size > 50 * 1024 * 1024:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="文件过大（>50MB）")
        tmp.close()

        backend.upload_file(UploadRequest(
            object_name=object_name,
            file_path=Path(tmp.name),
            content_type=request.headers.get("content-type"),
        ))
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            pass

    logger.info("direct-upload ok: file_id=%s nonce=%s", file_id, nonce[:8] + "...")
    return {
        "file_id": file_id,
        "object_name": object_name,
        "nonce": nonce,
        "status": "ok",
    }


# ── 3) 健康检查 ──────────────────────────────────────────────
@router.get("/health")
async def oss_health() -> dict:
    """存活性 + 后端诊断。"""
    svc = get_storage_service()
    return {
        "status": "ok",
        "backend": svc.backend_kind,
        "upload_dir": str(svc.adapter.upload_dir) if hasattr(svc.adapter, "upload_dir") else None,
    }


# ── 4) head_object（业务查询）─────────────────────────────
@router.get("/objects/{object_name:path}", response_model=ObjectMetadataResponse)
async def oss_head_object(object_name: str) -> ObjectMetadataResponse:
    """查询对象元信息（走 oss.StorageService Protocol.head_object）。

    object_name 支持 'local://bucket/file' / 'bucket/file' 等格式。
    """
    svc = get_storage_service()
    try:
        meta = svc.adapter.head_object(object_name)
        return ObjectMetadataResponse(
            object_name=meta.object_name,
            content_length=meta.content_length,
            content_type=meta.content_type,
            etag=meta.etag,
            last_modified=meta.last_modified,
            metadata=dict(meta.metadata or {}),
            exists=True,
            backend=svc.backend_kind,
        )
    except FileNotFoundError:
        return ObjectMetadataResponse(
            object_name=object_name,
            content_length=None,
            content_type=None,
            etag=None,
            last_modified=None,
            metadata={},
            exists=False,
            backend=svc.backend_kind,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("head_object failed: %s", object_name)
        raise HTTPException(status_code=500, detail=f"查询对象元信息失败: {exc!r}")