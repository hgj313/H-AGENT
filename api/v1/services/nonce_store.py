"""
NonceStore —— presign-upload 防重放 nonce 存储。

设计：
  presign-upload 时，后端生成 nonce（UUID v4），写入本表，状态 = 'issued'。
  客户端 PUT 直传时必须带 X-Nonce header，后端：
    1. 查 nonce 是否存在
    2. 校验 nonce.file_id 与 URL 中的 file_id 一致（防跨 file 滥用）
    3. 校验 nonce 未过期
    4. 校验 nonce 未被消费（consumed_at IS NULL）
    5. 原子地标记 consumed_at = now（SQLite 单 UPDATE）
  任一步失败 → 403/409，拒绝上传。

防重放效果：
  - 同 nonce 二次消费：consumed_at != NULL → 拒绝
  - 同 nonce 跨越 file_id：file_id mismatch → 拒绝
  - 过期 nonce：expires_at < now → 拒绝
  - 猜测 nonce：UUID v4 (122 bit entropy) → 不可能
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import uuid


_DEFAULT_DB_PATH = Path("db") / "upload_nonce.db"
_lock = threading.Lock()


class NonceStoreError(Exception):
    """Nonce 验证失败（消费/过期/不匹配等业务级错误）。"""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class NonceStore:
    """基于 SQLite 的 nonce 一次性消费存储。

    用法：
        store = NonceStore()
        store.issue("abc", file_id="file-xxx", object_name="local://b/f.png",
                    backend="local", ttl_seconds=600)
        try:
            store.consume("abc", file_id="file-xxx")  # 第二次会抛 NonceStoreError
        except NonceStoreError as e:
            print(e.code, e.message)
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_nonce (
                    nonce TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    object_name TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    consumed_at REAL
                )
                """
            )
            # 索引：加速 cleanup_expired 和按 file_id 查询
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_nonce_expires ON upload_nonce(expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_nonce_file_id ON upload_nonce(file_id)"
            )
            conn.commit()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def new_nonce() -> str:
        """生成新 nonce（UUID v4，hex，32 字符）。"""
        return uuid.uuid4().hex

    def issue(
        self,
        nonce: str,
        *,
        file_id: str,
        object_name: str,
        backend: str,
        ttl_seconds: int,
        now: Optional[float] = None,
    ) -> None:
        """签发 nonce（写入数据库，状态 = issued，未消费）。"""
        now = now or time.time()
        expires_at = now + ttl_seconds
        with _lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO upload_nonce
                    (nonce, file_id, object_name, backend, created_at, expires_at, consumed_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (nonce, file_id, object_name, backend, now, expires_at),
            )

    def consume(
        self,
        nonce: str,
        *,
        file_id: str,
        now: Optional[float] = None,
    ) -> None:
        """原子消费 nonce。

        校验：
          1) nonce 存在
          2) file_id 与签发时一致
          3) 未过期
          4) 未被消费
        验证通过：标记 consumed_at = now（单 UPDATE 原子）。
        任一步失败 → 抛 NonceStoreError(code=..., message=...)。

        注：使用"UPDATE ... WHERE consumed_at IS NULL AND expires_at > ?"
        单条 SQL 是天然原子的，并发安全。
        """
        now = now or time.time()
        with _lock, self._conn() as conn:
            row = conn.execute(
                "SELECT file_id, expires_at, consumed_at FROM upload_nonce WHERE nonce = ?",
                (nonce,),
            ).fetchone()
            if row is None:
                raise NonceStoreError(
                    code="NONCE_NOT_FOUND",
                    message=f"nonce 不存在或已清理: {nonce[:8]}...",
                )
            if row["file_id"] != file_id:
                raise NonceStoreError(
                    code="NONCE_FILE_MISMATCH",
                    message=(
                        f"nonce 与 file_id 不匹配: nonce.file_id={row['file_id']!r} "
                        f"但 URL file_id={file_id!r}"
                    ),
                )
            if row["consumed_at"] is not None:
                raise NonceStoreError(
                    code="NONCE_ALREADY_CONSUMED",
                    message=f"nonce 已被消费: {nonce[:8]}...（consumed_at={row['consumed_at']}）",
                )
            if row["expires_at"] < now:
                raise NonceStoreError(
                    code="NONCE_EXPIRED",
                    message=f"nonce 已过期: {nonce[:8]}...（expires_at={row['expires_at']}, now={now}）",
                )
            # 原子标记消费
            cur = conn.execute(
                """
                UPDATE upload_nonce
                SET consumed_at = ?
                WHERE nonce = ? AND consumed_at IS NULL AND expires_at > ?
                """,
                (now, nonce, now),
            )
            if cur.rowcount == 0:
                # 极端并发场景：查的时候未消费，更新时已被消费
                raise NonceStoreError(
                    code="NONCE_RACE_CONSUMED",
                    message=f"nonce 消费竞争失败: {nonce[:8]}...（并发场景）",
                )

    def cleanup_expired(self, now: Optional[float] = None) -> int:
        """清理过期且已消费的记录，返回删除条数。

        不清理过期但未消费的（理论上不应该出现，除非 clock skew），
        因为 nonce 应在过期后由下一次 issue 覆盖。
        """
        now = now or time.time()
        with _lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM upload_nonce WHERE expires_at < ?",
                (now,),
            )
            return cur.rowcount

    def count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM upload_nonce").fetchone()
            return int(row["c"] or 0)

    def clear_all(self) -> None:
        """清空所有记录（用于测试 setup）。"""
        with _lock, self._conn() as conn:
            conn.execute("DELETE FROM upload_nonce")


# ── Module singleton ─────────────────────────────────────────
_store: NonceStore | None = None


def get_nonce_store() -> NonceStore:
    """获取全局 NonceStore 单例。"""
    global _store
    if _store is None:
        _store = NonceStore()
    return _store