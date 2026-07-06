"""
存储服务层 - 基于项目 oss 模块的领域封装。

设计原则：
  - 复用项目已有 oss/base.py 的 StorageService Protocol 与全套 dataclass
  - 复用 oss/aliyun_oss.py 的 AliyunOSSAdapter（生产真 OSS）
  - 复用 oss/di.py 的 OSSRegistry + provide_oss_client（env 自动激活）
  - 本文件新增 LocalStorageBackend 作为 dev/test 兜底
  - 领域层只暴露 upload_for_review / presign 等业务方法，不暴露 Protocol 细节

Backend 选择顺序（首次调用时确定，后续不变）：
  1. OSSRegistry 已注册 adapter（生产 = AliyunOSSAdapter 或测试 mock）
  2. provide_oss_client() 从 env 加载（设置 OSS_* 即可激活真 OSS）
  3. 兜底 LocalStorageBackend（开发/测试/CI 离线场景）
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional

from fastapi import HTTPException, UploadFile

# 复用项目既有抽象
from oss.base import (
    DownloadRequest,
    DownloadResult,
    ObjectMetadata,
    PublicURLRequest,
    PublicURLResult,
    SignedURLRequest,
    SignedURLResult,
    StorageService as StorageServiceProtocol,  # Protocol（接口）
    StreamDownloadRequest,
    UploadRequest,
    UploadResult,
)
from oss.di import OSSRegistry, provide_oss_client

from api.v1.schemas.files import ALLOWED_EXTENSIONS, FileType, MAX_FILE_SIZE
from api.v1.schemas.oss import OSSUploadResponse, default_expires_at

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

DEFAULT_URL_TTL_SECONDS = 3600

# 幂等性 DB 路径（与 chat.db 同根，便于复用一个项目）
_IDEMPOTENCY_DB_PATH = Path("db") / "oss_idempotency.db"
_IDEMPOTENCY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_idempotency_lock = threading.Lock()


# ── 1) LocalStorageBackend：实现 oss.StorageService Protocol ───────
class LocalStorageBackend:
    """本地存储后端，实现 oss.base.StorageService Protocol。

    适用：开发、CI、单元测试。
    生产应通过 OSSRegistry.register(AliyunOSSAdapter.from_config(...)) 激活真 OSS。
    """

    backend_name: str = "local"

    def __init__(self, upload_dir: Path | None = None):
        self.upload_dir = upload_dir or UPLOAD_DIR
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        logger.info("LocalStorageBackend 初始化：upload_dir=%s", self.upload_dir)

    @staticmethod
    def _parse_object_name(object_name: str) -> tuple[str, str]:
        """object_name -> (bucket, filename)。"""
        rest = object_name
        if rest.startswith("local://"):
            rest = rest[len("local://"):]
        if "/" not in rest:
            raise ValueError(f"非法 object_name: {object_name!r}（期望 'bucket/filename'）")
        bucket, filename = rest.split("/", 1)
        return bucket, filename

    def _resolve_path(self, object_name: str) -> Path:
        bucket, filename = self._parse_object_name(object_name)
        return self.upload_dir / bucket / filename

    @staticmethod
    def _file_id_from_object(object_name: str) -> str:
        """object_name 末段的 file_id（去掉扩展名）。"""
        _bucket, filename = LocalStorageBackend._parse_object_name(object_name)
        return filename.split(".", 1)[0]

    # ── StorageService Protocol 实现 ────────────────────────
    def upload_file(self, request: UploadRequest) -> UploadResult:
        """普通上传。"""
        target = self._resolve_path(request.object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(request.file_path, "rb") as src, open(target, "wb") as dst:
            while True:
                chunk = src.read(64 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
        logger.info("Local upload: %s -> %s (%d bytes)", request.object_name, target, target.stat().st_size)
        return UploadResult(
            object_name=request.object_name,
            etag=None,
            version_id=None,
        )

    def multipart_upload(self, request) -> UploadResult:
        """Local 不分片，等价普通上传。"""
        return self.upload_file(request)  # type: ignore[arg-type]

    def resumable_upload(self, request) -> UploadResult:
        """Local 无续传概念，等价普通上传。"""
        return self.upload_file(request)  # type: ignore[arg-type]

    def upload_stream(self, request) -> UploadResult:
        """流式上传：从 reader 写入目标文件。"""
        target = self._resolve_path(request.object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as dst:
            while chunk := request.reader.read(64 * 1024):
                dst.write(chunk)
        return UploadResult(
            object_name=request.object_name,
            etag=None,
            version_id=None,
        )

    def download_file(self, request: DownloadRequest) -> DownloadResult:
        """下载到本地路径。"""
        src = self._resolve_path(request.object_name)
        target = Path(request.target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as fsrc, open(target, "wb") as fdst:
            while chunk := fsrc.read(64 * 1024):
                fdst.write(chunk)
        return DownloadResult(
            object_name=request.object_name,
            target_path=str(target),
            written_bytes=target.stat().st_size,
        )

    def stream_download(self, request: StreamDownloadRequest) -> Iterator[bytes]:
        """流式下载。"""
        src = self._resolve_path(request.object_name)
        with open(src, "rb") as f:
            while chunk := f.read(request.chunk_size):
                yield chunk

    def generate_signed_url(self, request: SignedURLRequest) -> SignedURLResult:
        """Local backend 的 URL 直拼 /api/v1/files/{file_id}/raw。

        注意：返回的是 **相对路径**（无 host/scheme）。
        如果上层需要完整 URL（前端 OSS 上传后取的可外网 fetch URL），
        应当走 get_public_url()，或者在 storage_service.upload_for_review 处
        基于 request base_url 拼成完整 URL。

        历史上曾用 /api/v1/files/{file_id}（元数据 JSON 端点），
        现改为 /api/v1/files/{file_id}/raw（字节流端点，视觉模型 fetch 用）。
        """
        file_id = self._file_id_from_object(request.object_name)
        return SignedURLResult(
            object_name=request.object_name,
            url=f"/api/v1/files/{file_id}/raw",
            method=request.method,
            expires_at=default_expires_at(request.expire_seconds),
            signed_headers={},
        )

    def get_public_url(self, request: PublicURLRequest) -> PublicURLResult:
        """Local backend 无 CDN，返回 /api/v1/files/{file_id}/raw（与 generate_signed_url 一致）。"""
        file_id = self._file_id_from_object(request.object_name)
        return PublicURLResult(
            object_name=request.object_name,
            url=f"/api/v1/files/{file_id}/raw",
            cdn_url=None,
        )

    def head_object(self, object_name: str) -> ObjectMetadata:
        """查询对象元信息。"""
        path = self._resolve_path(object_name)
        if not path.exists():
            raise FileNotFoundError(f"object 不存在: {object_name}")
        stat = path.stat()
        return ObjectMetadata(
            object_name=object_name,
            content_length=stat.st_size,
            content_type=None,
            etag=None,
            last_modified=None,
            metadata={},
        )


# ── 2) 领域服务：把 FastAPI UploadFile 适配到 oss.StorageService ───────


class IdempotencyStore:
    """基于 SQLite 的上传幂等性去重存储。

    同一文件（content_hash）第二次上传时复用先前的 object_name。
    Key: SHA-256(content)  Value: object_name + file_id + expires_at

    线程安全：单连接 + lock，SQLite 自带事务。
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or _IDEMPOTENCY_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with _idempotency_lock, self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_dedup (
                    content_hash TEXT PRIMARY KEY,
                    object_name  TEXT NOT NULL,
                    file_id      TEXT NOT NULL,
                    file_size    INTEGER NOT NULL,
                    file_type    TEXT,
                    filename     TEXT,
                    backend      TEXT NOT NULL,
                    created_at   REAL NOT NULL,
                    expires_at   REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_upload_dedup_created_at "
                "ON upload_dedup(created_at)"
            )

    def get(self, content_hash: str) -> Optional[dict]:
        """按 hash 查 object_name，None = 未命中。"""
        with _idempotency_lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM upload_dedup WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def put(
        self,
        content_hash: str,
        object_name: str,
        file_id: str,
        file_size: int,
        file_type: str,
        filename: str,
        backend: str,
        expires_at: Optional[float] = None,
    ) -> None:
        with _idempotency_lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO upload_dedup
                (content_hash, object_name, file_id, file_size, file_type,
                 filename, backend, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_hash, object_name, file_id, file_size, file_type,
                    filename, backend, time.time(), expires_at,
                ),
            )

    def cleanup_expired(self, now: Optional[float] = None) -> int:
        """清理过期记录（expires_at < now）。返回删除条数。"""
        now = now or time.time()
        with _idempotency_lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM upload_dedup WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            return cur.rowcount

    def count(self) -> int:
        with _idempotency_lock, self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM upload_dedup").fetchone()
            return int(row["c"] or 0)

    def clear_all(self) -> None:
        """清空所有记录（用于测试 setup / 运维重置）。

        不会删除文件本身（避免 Windows 上文件锁导致的 unlink 失败）。
        """
        with _idempotency_lock, self._conn() as conn:
            conn.execute("DELETE FROM upload_dedup")
            conn.commit()


# 全局幂等性 store 单例
_idempotency_store: IdempotencyStore | None = None


def get_idempotency_store() -> IdempotencyStore:
    global _idempotency_store
    if _idempotency_store is None:
        _idempotency_store = IdempotencyStore()
    return _idempotency_store


class StorageService:
    """领域存储服务（包装 oss.StorageService Protocol）。

    Backend 选择：
      1. 优先 OSSRegistry 已注册的 adapter
      2. 再试 provide_oss_client()（env 自动激活）
      3. 兜底 LocalStorageBackend

    该类在第一次请求时确定 backend 类型（懒初始化）。
    """

    def __init__(self):
        self._adapter: StorageServiceProtocol | None = None
        self._backend_kind: str = "uninitialized"

    def _get_adapter(self) -> StorageServiceProtocol:
        if self._adapter is not None:
            return self._adapter

        # 1) OSSRegistry 已注册
        try:
            adapter = OSSRegistry.get_instance().get_adapter()
            self._adapter = adapter
            self._backend_kind = "oss"
            logger.info("StorageService: 使用 OSSRegistry 已注册的 adapter (%s)", type(adapter).__name__)
            return adapter
        except RuntimeError:
            pass

        # 2) env 自动加载
        try:
            provide_oss_client()
            adapter = OSSRegistry.get_instance().get_adapter()
            self._adapter = adapter
            self._backend_kind = "oss"
            logger.info("StorageService: 从 env 激活 AliyunOSSAdapter")
            return adapter
        except RuntimeError as exc:
            logger.debug("StorageService: env 加载失败 (%s)，回退 Local", exc)

        # 3) 兜底 Local
        self._adapter = LocalStorageBackend()
        self._backend_kind = "local"
        logger.info("StorageService: 使用 LocalStorageBackend（OSS 未注册且无环境变量）")
        return self._adapter

    @property
    def backend_kind(self) -> str:
        self._get_adapter()  # ensure initialized
        return self._backend_kind

    @property
    def adapter(self) -> StorageServiceProtocol:
        """暴露底层 adapter（用于测试 / 高级用法）。"""
        return self._get_adapter()

    async def upload_for_review(
        self,
        file: UploadFile,
        *,
        bucket: str = "default",
        ttl_seconds: int = DEFAULT_URL_TTL_SECONDS,
    ) -> "OSSUploadResponse":
        """领域方法：上传 + 签发 URL，返回 OSSUploadResponse。

        ⚠️ 已被 POST /api/v1/oss/presign-upload 取代。
        保留仅为向后兼容 —— 推荐走新流程（申请许可 → PUT 直传 → 用 public_url）。

        Idempotency 不再支持（新流程里客户端拿整个文件 PUT，无法服务端去重）。
        """
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名为空")

        # 1) 校验扩展名
        ext = Path(file.filename).suffix.lower()
        file_type: FileType | None = None
        for ft, exts in ALLOWED_EXTENSIONS.items():
            if ext in exts:
                file_type = ft
                break
        if file_type is None:
            allowed = sorted({e for s in ALLOWED_EXTENSIONS.values() for e in s})
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型 '{ext}'，允许: {', '.join(allowed)}",
            )

        # 2) 读 + 校验大小
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            mb = MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(
                status_code=400,
                detail=f"文件大小超过限制，最大允许 {mb}MB",
            )

        # 3) 上传
        import uuid as _uuid
        file_id = f"file-{_uuid.uuid4().hex[:12]}"
        saved_filename = f"{file_id}{ext}"
        adapter = self._get_adapter()
        backend_kind = self._backend_kind
        if backend_kind == "local":
            object_name = f"local://{bucket}/{saved_filename}"
        else:
            object_name = f"{bucket}/{saved_filename}"

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            adapter.upload_file(UploadRequest(
                object_name=object_name,
                file_path=tmp_path,
                content_type=file.content_type,
            ))
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

        signed = adapter.generate_signed_url(SignedURLRequest(
            object_name=object_name,
            expire_seconds=ttl_seconds,
        ))
        return OSSUploadResponse(
            object_name=object_name,
            url=signed.url,
            expires_at=signed.expires_at or default_expires_at(ttl_seconds),
            file_id=file_id,
            filename=file.filename,
            file_type=file_type,
            file_size=len(content),
            storage_backend=backend_kind,
            idempotent_reused=False,
            content_hash=None,
        )

    def presign(
        self,
        object_name: str,
        *,
        ttl_seconds: int = DEFAULT_URL_TTL_SECONDS,
    ) -> dict:
        """领域方法：重新签发 URL。

        ⚠️ 已被 POST /api/v1/oss/presign-upload 取代。保留仅为向后兼容。
        """
        adapter = self._get_adapter()
        signed = adapter.generate_signed_url(SignedURLRequest(
            object_name=object_name,
            expire_seconds=ttl_seconds,
        ))
        return {
            "url": signed.url,
            "expires_at": signed.expires_at,
        }


# ── Module singleton ─────────────────────────────────────────
_service: StorageService | None = None


def get_storage_service() -> StorageService:
    """获取领域存储服务单例。"""
    global _service
    if _service is None:
        _service = StorageService()
    return _service
