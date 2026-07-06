"""
LongTermStore - 长期记忆事实存储

设计要点：
- 单一职责：只做事实的增/查，不做 LLM 抽取
- 存储后端：复用项目 SQLite（database.py 的同一份 chat.db）
- 检索：先精确子串匹配（LIKE），失败时退化为关键词 OR 匹配
- 去重：(user_id, fact_text) UNIQUE 约束

为什么不上 vector DB：
- chromadb 已在 deps，但首次启动会下载 embedding 模型（数 GB）
- MVP 阶段事实量小（每用户几十条），SQLite LIKE 足够
- 升级路径：保留 LongTermStore 抽象，未来切换成 VectorLongTermStore
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LongTermStore:
    """长期记忆事实存储。表名：long_term_facts。"""

    TABLE = "long_term_facts"

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        from api.v1.services.database import DB_PATH

        self.db_path = Path(db_path) if db_path else DB_PATH
        self._init_schema()

    # ── Schema ─────────────────────────────────────────────────────
    def _init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    fact_text TEXT NOT NULL,
                    category TEXT DEFAULT 'other',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, fact_text)
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.TABLE}_user "
                f"ON {self.TABLE}(user_id)"
            )
            conn.commit()

    # ── 写入 ───────────────────────────────────────────────────────
    def add_fact(self, user_id: str, fact_text: str, category: str = "other") -> bool:
        """新增一条事实。重复（同一 user_id+fact_text）静默忽略。"""
        if not user_id or not fact_text or not fact_text.strip():
            return False
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    f"INSERT OR IGNORE INTO {self.TABLE} "
                    "(user_id, fact_text, category, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, fact_text.strip(), category, str(time.time())),
                )
                conn.commit()
            return True
        except sqlite3.Error as exc:
            logger.warning("LongTermStore.add_fact 失败: %s", exc)
            return False

    def add_facts_bulk(
        self, user_id: str, facts: list[dict[str, Any]]
    ) -> int:
        """批量新增。facts: [{text, category?}, ...] 返回写入条数。"""
        count = 0
        for f in facts:
            text = f.get("text", "").strip()
            if not text:
                continue
            if self.add_fact(user_id, text, f.get("category", "other")):
                count += 1
        return count

    # ── 检索 ───────────────────────────────────────────────────────
    def search(
        self, user_id: str, query: str, limit: int = 5
    ) -> list[dict[str, str]]:
        """按 query 关键词检索该用户的事实。

        策略：
        1. 先全串子串匹配（query 整体出现在 fact_text）
        2. 不足 limit 时，按空格/中文标点切词 OR 补足
        3. 始终按 id 倒序（新事实优先）
        """
        if not user_id or not query:
            return []
        keywords = _tokenize(query)
        with sqlite3.connect(self.db_path) as conn:
            # 1) 整体子串
            rows = conn.execute(
                f"SELECT fact_text, category, created_at FROM {self.TABLE} "
                "WHERE user_id=? AND fact_text LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, f"%{query.strip()}%", limit),
            ).fetchall()
            if len(rows) >= limit or not keywords:
                return [_row_to_dict(r) for r in rows]

            # 2) 关键词 OR 补足
            placeholders = " OR ".join(["fact_text LIKE ?"] * len(keywords))
            like_params = [f"%{kw}%" for kw in keywords]
            params: list[Any] = [user_id, *like_params, limit]
            rows2 = conn.execute(
                f"SELECT DISTINCT fact_text, category, created_at "
                f"FROM {self.TABLE} "
                f"WHERE user_id=? AND ({placeholders}) "
                f"ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        # 去重（同时匹配 1 和 2 的）
        seen = set()
        merged: list[dict[str, str]] = []
        for r in list(rows) + list(rows2):
            d = _row_to_dict(r)
            if d["text"] in seen:
                continue
            seen.add(d["text"])
            merged.append(d)
            if len(merged) >= limit:
                break
        return merged

    def get_all(self, user_id: str, limit: int = 100) -> list[dict[str, str]]:
        """取该用户全部事实（管理/调试用）。"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT fact_text, category, created_at FROM {self.TABLE} "
                "WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def count(self, user_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {self.TABLE} WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return int(row[0]) if row else 0


def _row_to_dict(row: tuple) -> dict[str, str]:
    return {"text": row[0], "category": row[1] or "other", "created_at": row[2] or ""}


def _tokenize(query: str) -> list[str]:
    """简单分词：英文按词 + 中文滑动 2-3 字片段。MVP 阶段够用。

    实现：使用 lookahead 取得所有 2-char / 3-char 重叠片段。
    为什么不用 {2,4} 非重叠：会导致 "黄国俊是谁？" 贪婪匹配为 ["黄国俊是"]，
    单一 keyword 在 SQL LIKE OR 中无法命中 "用户名叫黄国俊"。
    """
    if not query:
        return []
    out: list[str] = []
    import re

    # 英文/数字 词
    for m in re.finditer(r"[A-Za-z0-9]+", query):
        out.append(m.group(0))
    # 中文 2-char / 3-char 重叠片段（lookahead 不消耗字符）
    for size in (2, 3):
        for m in re.finditer(rf"(?=([\u4e00-\u9fff]{{{size}}}))", query):
            out.append(m.group(1))
    # 短中文（1 字）独立成词，但仅当 query 短时
    if len(query) <= 4:
        for ch in query:
            if "\u4e00" <= ch <= "\u9fff" and ch not in out:
                out.append(ch)
    return list(dict.fromkeys(out))  # 去重保序
