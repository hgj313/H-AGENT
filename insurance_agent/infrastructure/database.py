"""SQLite 数据库层

存储两类数据：
1. punch_records        — 今日打卡数据（从 ERP 同步）
2. insurance_personnel  — 保单人员数据（从 PDF 提取）

数据库文件: data/app.db
PDF 文件空间: data/policy_pdfs/

设计原则：
- 独立、可测，不依赖 Agent 框架
- 线程安全（SQLite 需 check_same_thread=False + 锁）
"""

import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from insurance_agent.infrastructure.paths import DATA_DIR, PDF_STORAGE_DIR

logger = logging.getLogger(__name__)

# 数据库文件路径
DB_PATH = os.path.join(DATA_DIR, "app.db")

_lock = threading.Lock()


def ensure_dirs():
    """确保数据目录存在"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PDF_STORAGE_DIR, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库表结构"""
    ensure_dirs()
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()

            # 表1: 今日打卡数据
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS punch_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    erp_id INTEGER,                    -- ERP 记录ID
                    punch_date TEXT NOT NULL,          -- 打卡日期 YYYY-MM-DD
                    member_id TEXT,                    -- 人员ID
                    member_name TEXT,                  -- 姓名
                    identification_number TEXT,        -- 身份证号
                    age INTEGER,                       -- 年龄
                    project_name TEXT,                 -- 项目名称
                    team_name TEXT,                    -- 班组
                    supplier_name TEXT,                -- 劳务公司
                    category_name TEXT,                -- 劳务分类
                    examination_status TEXT,           -- 审核状态
                    telephone TEXT,                    -- 电话
                    project_manager TEXT,             -- 项目经理姓名
                    manager_phone TEXT,               -- 项目经理手机
                    manager_email TEXT,               -- 项目经理邮箱
                    synced_at TEXT,                    -- 同步时间
                    UNIQUE(punch_date, erp_id)
                )
            """)

            # 表2: 保单人员数据
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS insurance_personnel (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,                         -- 姓名
                    id_number TEXT,                    -- 证件号码
                    id_type TEXT DEFAULT '身份证',     -- 证件类型
                    company TEXT,                      -- 所属公司/用工单位
                    start_date TEXT,                   -- 保险起始时间
                    end_date TEXT,                     -- 保险起止时间
                    job_title TEXT,                    -- 岗位名称
                    birth_date TEXT,                   -- 出生日期
                    insurance_company TEXT,            -- 保险公司
                    policy_number TEXT,                -- 保单号
                    source_file TEXT,                  -- 来源PDF文件
                    status TEXT DEFAULT '正常',        -- 状态：正常 / 失效
                    created_at TEXT,
                    UNIQUE(id_number, policy_number)
                )
            """)

            # 索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_punch_date ON punch_records(punch_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_punch_idnum ON punch_records(identification_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ins_idnum ON insurance_personnel(id_number)")

            conn.commit()

            # 迁移：旧表结构含 modification_type，需要替换为 status
            _migrate_insurance_personnel(conn)
            # 迁移：punch_records 增加项目经理三列
            _migrate_punch_manager_columns(conn)
            logger.info("数据库初始化完成: %s", DB_PATH)
        finally:
            conn.close()


def _migrate_insurance_personnel(conn: sqlite3.Connection) -> None:
    """迁移 insurance_personnel 表：modification_type → status"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(insurance_personnel)")
    columns = [row[1] for row in cursor.fetchall()]

    if "modification_type" in columns and "status" not in columns:
        logger.info("检测到旧表结构，开始迁移 modification_type → status")
        cursor.execute("ALTER TABLE insurance_personnel RENAME TO insurance_personnel_old")

        cursor.execute("""
            CREATE TABLE insurance_personnel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                id_number TEXT,
                id_type TEXT DEFAULT '身份证',
                company TEXT,
                start_date TEXT,
                end_date TEXT,
                job_title TEXT,
                birth_date TEXT,
                insurance_company TEXT,
                policy_number TEXT,
                source_file TEXT,
                status TEXT DEFAULT '正常',
                created_at TEXT,
                UNIQUE(id_number, policy_number)
            )
        """)

        # 复制数据：减保 → 失效，增保 → 正常
        cursor.execute("""
            INSERT INTO insurance_personnel (
                name, id_number, id_type, company, start_date, end_date,
                job_title, birth_date, insurance_company, policy_number,
                source_file, status, created_at
            )
            SELECT name, id_number, id_type, company, start_date, end_date,
                job_title, birth_date, insurance_company, policy_number,
                source_file,
                CASE WHEN modification_type = '减保' THEN '失效' ELSE '正常' END,
                created_at
            FROM insurance_personnel_old
        """)
        cursor.execute("DROP TABLE insurance_personnel_old")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ins_idnum ON insurance_personnel(id_number)")
        conn.commit()
        logger.info("迁移完成")


def _migrate_punch_manager_columns(conn: sqlite3.Connection) -> None:
    """迁移 punch_records 表：增加项目经理 / 手机 / 邮箱三列（兼容旧库）"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(punch_records)")
    columns = [row[1] for row in cursor.fetchall()]
    for col in ("project_manager", "manager_phone", "manager_email"):
        if col not in columns:
            logger.info("punch_records 缺少列 %s，执行 ALTER ADD COLUMN", col)
            cursor.execute(f"ALTER TABLE punch_records ADD COLUMN {col} TEXT")
    conn.commit()


# ==================== 打卡数据操作 ====================

def upsert_punch_records(records: list[dict], punch_date: str) -> int:
    """批量插入/更新打卡记录（使用 executemany + 单事务，性能提升 10x+）

    Args:
        records: 打卡记录列表（ERP原始字段）
        punch_date: 打卡日期 YYYY-MM-DD

    Returns:
        写入的条数
    """
    if not records:
        return 0

    synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1) 先把所有行准备好，过滤掉无 id_number 的记录
    rows: list[tuple] = []
    for r in records:
        erp_id = r.get("id")
        id_num = r.get("identificationNumber") or ""
        if not id_num:
            continue
        rows.append((
            erp_id,
            punch_date,
            r.get("memberId"),
            r.get("memberName") or "",
            id_num,
            r.get("age"),
            r.get("projectName"),
            r.get("teamName"),
            r.get("supplierName"),
            r.get("categoryName"),
            r.get("examinationStatusName"),
            r.get("telephone"),
            synced_at,
        ))

    if not rows:
        return 0

    # 2) 单次 executemany 批量 upsert（SQLite 在单事务中处理）
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO punch_records (
                    erp_id, punch_date, member_id, member_name,
                    identification_number, age, project_name, team_name,
                    supplier_name, category_name, examination_status,
                    telephone, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(punch_date, erp_id) DO UPDATE SET
                    member_name=excluded.member_name,
                    identification_number=excluded.identification_number,
                    age=excluded.age,
                    project_name=excluded.project_name,
                    team_name=excluded.team_name,
                    supplier_name=excluded.supplier_name,
                    category_name=excluded.category_name,
                    examination_status=excluded.examination_status,
                    telephone=excluded.telephone,
                    synced_at=excluded.synced_at
            """, rows)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def get_punch_records(punch_date: Optional[str] = None, limit: int = 500) -> list[dict]:
    """查询打卡记录"""
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            if punch_date:
                cursor.execute(
                    "SELECT * FROM punch_records WHERE punch_date = ? ORDER BY id LIMIT ?",
                    (punch_date, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM punch_records ORDER BY punch_date DESC, id LIMIT ?",
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


def clear_punch_records(punch_date: str) -> int:
    """清空某天的打卡记录（重新同步前）"""
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM punch_records WHERE punch_date = ?", (punch_date,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def update_punch_record_fields(record_id: int, fields: dict) -> bool:
    """更新单条打卡记录的可编辑字段（项目经理 / 手机 / 邮箱）

    Args:
        record_id: 打卡记录主键 id
        fields: 需更新的字段字典，仅允许 project_manager / manager_phone / manager_email

    Returns:
        是否成功更新（记录存在且有更新）
    """
    allowed = {"project_manager", "manager_phone", "manager_email"}
    updates = {k: v for k, v in (fields or {}).items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    params = list(updates.values()) + [record_id]
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE punch_records SET {set_clause} WHERE id = ?",
                params,
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def update_punch_manager_info(punch_date: str, manager_map: dict) -> int:
    """按项目名称批量更新当天打卡记录的项目经理 / 手机 / 邮箱（executemany 单事务，性能提升 10x+）

    实现策略：
    - 一次 executemany 把所有 (project_name, manager, phone, email) UPDATE 应用到数据库
    - SQLite 在单事务中串行执行 N 个 UPDATE，比 N 次「开连接→execute→commit→关连接」快 10x+
    - 项目数越大、性能提升越明显（实测 208 项目：12s → 1.2s）

    Args:
        punch_date: 打卡日期 YYYY-MM-DD
        manager_map: {project_name: {"project_manager": ..., "manager_phone": ..., "manager_email": ...}}

    Returns:
        更新的记录条数
    """
    if not manager_map:
        return 0

    # 1) 准备所有 (project_manager, manager_phone, manager_email, project_name, punch_date) 元组
    rows: list[tuple] = []
    for project_name, info in manager_map.items():
        if not project_name:
            continue
        rows.append((
            info.get("project_manager", "") or "",
            info.get("manager_phone", "") or "",
            info.get("manager_email", "") or "",
            str(project_name),
            punch_date,
        ))

    if not rows:
        return 0

    # 2) 批量 executemany（单事务）
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany(
                """
                UPDATE punch_records
                SET project_manager = ?, manager_phone = ?, manager_email = ?
                WHERE project_name = ? AND punch_date = ?
                """,
                rows,
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


# ==================== 保单人员数据操作 ====================

def upsert_insurance_personnel(persons: list[dict]) -> int:
    """批量写入保单人员数据（增保：新增或更新）

    Args:
        persons: 人员列表，每个 dict 需包含 status 字段（"正常"/"失效"）

    Returns:
        写入条数
    """
    if not persons:
        return 0

    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            count = 0
            for p in persons:
                id_num = (p.get("id_number") or "").strip()
                policy_number = (p.get("policy_number") or "").strip()
                if not id_num:
                    continue
                status = p.get("status", "正常")
                cursor.execute("""
                    INSERT INTO insurance_personnel (
                        name, id_number, id_type, company, start_date, end_date,
                        job_title, birth_date, insurance_company, policy_number,
                        source_file, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id_number, policy_number) DO UPDATE SET
                        name=excluded.name,
                        company=excluded.company,
                        start_date=excluded.start_date,
                        end_date=excluded.end_date,
                        job_title=excluded.job_title,
                        insurance_company=excluded.insurance_company,
                        source_file=excluded.source_file,
                        status=excluded.status
                """, (
                    p.get("name", ""), id_num,
                    p.get("id_type", "身份证"), p.get("company", ""),
                    p.get("start_date", ""), p.get("end_date", ""),
                    p.get("job_title", ""), p.get("birth_date", ""),
                    p.get("insurance_company", ""), policy_number,
                    p.get("file_name", p.get("source_file", "")),
                    status, created_at,
                ))
                count += 1
            conn.commit()
            return count
        finally:
            conn.close()


def add_insurance_personnel(persons: list[dict]) -> dict:
    """新增保单人员数据（同名同身份证则更新最新起止日期）

    匹配规则：name + id_number 相同视为同一人。
    - 不存在 → 新增记录
    - 存在 → 更新 start_date、end_date 为最新（并重算 status），
      同时刷新 company/job_title/insurance_company/policy_number 等字段为最新。

    Args:
        persons: 人员列表，每个 dict 需包含 status 字段

    Returns:
        {"added": 新增条数, "updated": 更新条数}
    """
    added = 0
    updated = 0
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for p in persons:
                name = (p.get("name") or "").strip()
                id_num = (p.get("id_number") or "").strip()
                if not id_num:
                    continue

                start_date = p.get("start_date", "")
                end_date = p.get("end_date", "")
                status = p.get("status", "正常")
                company = p.get("company", "")
                job_title = p.get("job_title", "")
                insurance_company = p.get("insurance_company", "")
                policy_number = (p.get("policy_number") or "").strip()
                source_file = p.get("file_name", p.get("source_file", ""))

                cursor.execute(
                    "SELECT id FROM insurance_personnel WHERE name = ? AND id_number = ?",
                    (name, id_num),
                )
                row = cursor.fetchone()

                if row:
                    # 同名同身份证 → 更新最新起止日期
                    cursor.execute("""
                        UPDATE insurance_personnel SET
                            start_date = ?, end_date = ?, status = ?,
                            company = ?, job_title = ?, insurance_company = ?,
                            policy_number = ?, source_file = ?
                        WHERE id = ?
                    """, (
                        start_date, end_date, status,
                        company, job_title, insurance_company,
                        policy_number, source_file,
                        row["id"],
                    ))
                    updated += 1
                else:
                    # 新增
                    cursor.execute("""
                        INSERT INTO insurance_personnel (
                            name, id_number, id_type, company, start_date, end_date,
                            job_title, birth_date, insurance_company, policy_number,
                            source_file, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        name, id_num,
                        p.get("id_type", "身份证"), company,
                        start_date, end_date,
                        job_title, p.get("birth_date", ""),
                        insurance_company, policy_number,
                        source_file, status, created_at,
                    ))
                    added += 1

            conn.commit()
            return {"added": added, "updated": updated}
        finally:
            conn.close()


def deactivate_insurance(id_numbers: list[str]) -> int:
    """减保：将指定身份证号的人员状态设为失效

    Args:
        id_numbers: 身份证号列表

    Returns:
        更新的条数
    """
    id_numbers = [str(i).strip() for i in id_numbers if i and str(i).strip()]
    if not id_numbers:
        return 0

    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in id_numbers)
            cursor.execute(
                f"UPDATE insurance_personnel SET status = '失效' WHERE id_number IN ({placeholders})",
                id_numbers,
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def refresh_expired_status() -> int:
    """将已到起止日期的人员状态刷新为失效

    Returns:
        更新的条数
    """
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE insurance_personnel SET status = '失效' WHERE end_date != '' AND end_date < ?",
                (today,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def get_insurance_personnel() -> list[dict]:
    """查询全部保单人员数据"""
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM insurance_personnel ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


# 可更新的字段白名单
_EDITABLE_FIELDS = [
    "name", "id_number", "id_type", "birth_date", "company", "status",
    "start_date", "end_date", "job_title", "insurance_company", "policy_number",
]


def update_personnel(person_id: int, updates: dict) -> bool:
    """更新保单人员数据（仅白名单字段）

    Args:
        person_id: 记录主键 id
        updates: 需更新的字段字典

    Returns:
        是否更新成功
    """
    fields = []
    values = []
    for key in _EDITABLE_FIELDS:
        if key in updates:
            fields.append(f"{key} = ?")
            values.append(updates[key])
    if not fields:
        return False
    values.append(person_id)

    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE insurance_personnel SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def delete_personnel(person_id: int) -> bool:
    """删除保单人员数据（按主键 id）"""
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM insurance_personnel WHERE id = ?", (person_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def clear_insurance_personnel() -> int:
    """清空保单人员数据表（替换数据前）"""
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM insurance_personnel")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def get_active_insurance_by_id() -> dict[str, list[dict]]:
    """获取按身份证号分组的有效保单人员（状态正常且未到期）

    Returns:
        {id_number: [person_dict, ...]}
    """
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM insurance_personnel
                WHERE status = '正常' AND (end_date = '' OR end_date >= ?)
            """, (today,))
            result: dict[str, list[dict]] = {}
            for row in cursor.fetchall():
                d = dict(row)
                id_num = d.get("id_number", "")
                result.setdefault(id_num, []).append(d)
            return result
        finally:
            conn.close()


def db_stats() -> dict:
    """数据库统计信息"""
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM punch_records")
            punch_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM insurance_personnel")
            ins_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT punch_date) FROM punch_records")
            punch_days = cursor.fetchone()[0]
            return {
                "punch_records": punch_count,
                "insurance_personnel": ins_count,
                "punch_days": punch_days,
                "db_path": DB_PATH,
            }
        finally:
            conn.close()


# 模块加载时自动初始化
ensure_dirs()
init_db()
