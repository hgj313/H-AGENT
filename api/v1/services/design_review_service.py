"""
DesignReview 持久化服务 - 设计审查会话与报告。

复用项目 SQLite（chat.db）单文件存储，避免拆库。
表：
  dr_sessions: 会话元数据（dr_session_id, user_id, prd_path, image_urls, status, report_id, ...）
  dr_reports:  报告 JSON（report_id, dr_session_id, report_json, status, error, duration_ms, ...）
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 复用 chat.db；与 api/v1/services/database.py 同一份
DB_PATH = Path(__file__).parent.parent.parent.parent / "db" / "chat.db"

_SESSION_TABLE = "dr_sessions"
_REPORT_TABLE = "dr_reports"

_init_lock = threading.Lock()
_initialized = False


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _ensure_schema() -> None:
    """建表（幂等）。由首次调用触发。"""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        with _conn() as c:
            c.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_SESSION_TABLE} (
                    dr_session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_title TEXT,
                    prd_path TEXT,
                    image_urls JSON,
                    status TEXT DEFAULT 'pending',
                    report_id TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            c.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_REPORT_TABLE} (
                    report_id TEXT PRIMARY KEY,
                    dr_session_id TEXT NOT NULL,
                    report_json JSON,
                    status TEXT DEFAULT 'completed',
                    error TEXT,
                    duration_ms INTEGER,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (dr_session_id) REFERENCES {_SESSION_TABLE}(dr_session_id) ON DELETE CASCADE
                )
                """
            )
            c.execute(
                f"CREATE INDEX IF NOT EXISTS idx_dr_sessions_user ON {_SESSION_TABLE}(user_id, created_at DESC)"
            )
            c.execute(
                f"CREATE INDEX IF NOT EXISTS idx_dr_reports_session ON {_REPORT_TABLE}(dr_session_id, created_at DESC)"
            )
            c.commit()
        _initialized = True


class DesignReviewService:
    """设计审查持久化服务 - 纯 CRUD，不做业务逻辑。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_schema()

    # ── 会话 ──────────────────────────────────────────────
    def create_session(
        self,
        user_id: str,
        prd_path: str = "",
        image_urls: Optional[list[str]] = None,
        session_title: Optional[str] = None,
    ) -> dict[str, Any]:
        sid = f"dr-{uuid.uuid4().hex[:12]}"
        now = time.time()
        title = session_title or f"设计审查 {time.strftime('%m-%d %H:%M', time.localtime(now))}"
        with sqlite3.connect(self._db_path) as c:
            c.execute(
                f"INSERT INTO {_SESSION_TABLE} "
                "(dr_session_id, user_id, session_title, prd_path, image_urls, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    user_id,
                    title,
                    prd_path,
                    json.dumps(image_urls or [], ensure_ascii=False),
                    "pending",
                    now,
                    now,
                ),
            )
            c.commit()
        return self.get_session(sid)  # type: ignore[return-value]

    def get_session(self, dr_session_id: str) -> Optional[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as c:
            row = c.execute(
                f"SELECT * FROM {_SESSION_TABLE} WHERE dr_session_id=?", (dr_session_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    def update_session_status(
        self, dr_session_id: str, status: str, report_id: Optional[str] = None, error: Optional[str] = None
    ) -> None:
        with sqlite3.connect(self._db_path) as c:
            c.execute(
                f"UPDATE {_SESSION_TABLE} SET status=?, report_id=COALESCE(?, report_id), "
                "error=COALESCE(?, error), updated_at=? WHERE dr_session_id=?",
                (status, report_id, error, time.time(), dr_session_id),
            )
            c.commit()

    def list_sessions(self, user_id: str, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as c:
            rows = c.execute(
                f"SELECT * FROM {_SESSION_TABLE} WHERE user_id=? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    # ── 报告 ──────────────────────────────────────────────
    def save_report(
        self,
        dr_session_id: str,
        report_data: dict[str, Any],
        duration_ms: int = 0,
        status: str = "completed",
        error: Optional[str] = None,
    ) -> str:
        """保存完整报告，返回 report_id。"""
        rid = f"DR-{time.strftime('%Y%m%d-%H%M%S', time.localtime())}-{uuid.uuid4().hex[:6]}"
        with sqlite3.connect(self._db_path) as c:
            c.execute(
                f"INSERT INTO {_REPORT_TABLE} "
                "(report_id, dr_session_id, report_json, status, error, duration_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    dr_session_id,
                    json.dumps(report_data, ensure_ascii=False, default=str),
                    status,
                    error,
                    duration_ms,
                    time.time(),
                ),
            )
            c.commit()
        return rid

    def get_report(self, report_id: str) -> Optional[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as c:
            row = c.execute(
                f"SELECT * FROM {_REPORT_TABLE} WHERE report_id=?", (report_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_report(row)

    def get_report_by_session(self, dr_session_id: str) -> Optional[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as c:
            row = c.execute(
                f"SELECT * FROM {_REPORT_TABLE} WHERE dr_session_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (dr_session_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_report(row)

    # ── 内部 ──────────────────────────────────────────────
    @staticmethod
    def _row_to_session(row: tuple) -> dict[str, Any]:
        cols = [
            "dr_session_id",
            "user_id",
            "session_title",
            "prd_path",
            "image_urls",
            "status",
            "report_id",
            "error",
            "created_at",
            "updated_at",
        ]
        out = dict(zip(cols, row))
        # image_urls: JSON 字符串 -> list
        try:
            out["image_urls"] = json.loads(out.get("image_urls") or "[]")
        except Exception:  # noqa: BLE001
            out["image_urls"] = []
        return out

    @staticmethod
    def _row_to_report(row: tuple) -> dict[str, Any]:
        cols = [
            "report_id",
            "dr_session_id",
            "report_json",
            "status",
            "error",
            "duration_ms",
            "created_at",
        ]
        out = dict(zip(cols, row))
        try:
            out["report_data"] = json.loads(out.get("report_json") or "{}")
        except Exception:  # noqa: BLE001
            out["report_data"] = {}
        out.pop("report_json", None)
        return out
