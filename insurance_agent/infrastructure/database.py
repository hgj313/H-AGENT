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

logger = logging.getLogger(__name__)

# 数据目录
DATA_DIR = "C:/insurance-automation/data"
DB_PATH = os.path.join(DATA_DIR, "app.db")
PDF_STORAGE_DIR = os.path.join(DATA_DIR, "policy_pdfs")

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


# ==================== 打卡数据操作 ====================

def upsert_punch_records(records: list[dict], punch_date: str) -> int:
    """批量插入/更新打卡记录

    Args:
        records: 打卡记录列表（ERP原始字段）
        punch_date: 打卡日期 YYYY-MM-DD

    Returns:
        写入的条数
    """
    if not records:
        return 0

    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            synced_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            count = 0
            for r in records:
                erp_id = r.get("id")
                member_name = r.get("memberName") or ""
                id_num = r.get("identificationNumber") or ""
                # 只保留有身份证号的记录（用于匹配保单）
                if not id_num:
                    continue

                cursor.execute("""
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
                """, (
                    erp_id, punch_date,
                    r.get("memberId"), member_name,
                    id_num, r.get("age"),
                    r.get("projectName"), r.get("teamName"),
                    r.get("supplierName"), r.get("categoryName"),
                    r.get("examinationStatusName"), r.get("telephone"),
                    synced_at,
                ))
                count += 1
            conn.commit()
            return count
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
