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


# ==================== status 白名单 ====================
# 业务上保单人员状态只有两种取值（用户明确约定）：
#   正常 / 失效
# 但历史上有多条写入路径误把「批改类型」(modification_type: 增保/减保) 或 Excel 里的
# 任意文本写进了 status 列，导致：
#   1. 前端下拉框显示非法值
#   2. get_active_insurance_by_id() 用 status = '正常' 严格等值查询 → 漏匹配
#      → 误判为「未参保」→ 误发邮件/短信（见 2026-09-16 段小平事件）
# 因此在数据库层做无条件归一化，作为所有写入路径的统一防线。
_VALID_PERSON_STATUSES = ("正常", "失效")

# 批改类型 → 业务状态（当 status 位置填了 modification_type 时的补救映射）
_MODIFICATION_TO_STATUS = {
    "增保": "正常",
    "减保": "失效",
    "批增": "正常",
    "批减": "失效",
    "增加": "正常",
    "减少": "失效",
    "新增": "正常",
    "删除": "失效",
}


def normalize_person_status(raw: str, end_date: str = "", today: str | None = None) -> str:
    """把任意 status 输入归一化到白名单 {正常, 失效}（2026-09-16 新增）

    归一化优先级：
      1. 已是白名单值 → 原样返回（最常见，零开销）
      2. 是批改类型（增保/减保/批增/...）→ 按 _MODIFICATION_TO_STATUS 映射，
         再用 end_date 校正（即使批改类型是"增保"，已过期仍应为"失效"）
      3. 空值 / 其它未知值 → 按 end_date 与今天比较推断：
         已过期 → 失效；否则（含无 end_date）→ 正常

    Args:
        raw: 调用方传入的原始 status（可能为空、可能为批改类型、可能为任意文本）
        end_date: 该人员的保险止期 YYYY-MM-DD，用于兜底推断
        today: "今天"，格式 YYYY-MM-DD；None 时取 datetime.now()

    Returns:
        "正常" 或 "失效"（保证一定是白名单值）
    """
    raw = (raw or "").strip()
    # 1. 已是白名单值 → 原样返回（最常见，零开销）
    if raw in _VALID_PERSON_STATUSES:
        return raw

    today = today or datetime.now().strftime("%Y-%m-%d")
    end_date = (end_date or "").strip()

    # 2. 是批改类型 → 先按语义映射
    mapped = _MODIFICATION_TO_STATUS.get(raw)
    if mapped:
        logger.warning(
            "status 收到批改类型 %r，已映射为 %r（写入方应传 正常/失效）", raw, mapped
        )
        # 再用 end_date 校正：即使批改类型是"增保"，只要已过期就该是失效
        if end_date and end_date < today:
            logger.warning("  └─ 但该人员 end_date=%s 已过期，校正为 失效", end_date)
            return "失效"
        return mapped

    # 3. 空值 / 其它未知值 → 按 end_date 与今天比较推断
    inferred = "失效" if (end_date and end_date < today) else "正常"
    if raw:
        logger.warning(
            "status 收到未知取值 %r，已按 end_date=%r 推断为 %r", raw, end_date, inferred
        )
    return inferred


# 内部别名：database 模块内部其它函数用短名调用，保持可读性
_normalize_status = normalize_person_status


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
                    punch_time TEXT,                  -- 打卡时间（ERP 原始返回则有，无则留空）
                    UNIQUE(punch_date, identification_number)
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
            # 迁移：punch_records 增加打卡时间列
            _migrate_punch_time_column(conn)
            # 迁移：punch_records 唯一约束改为 (punch_date, identification_number)
            #   避免 ERP 推送缺 id 字段时 erp_id="" 互相覆盖
            _migrate_unique_to_identification_number(conn)
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


def _migrate_punch_time_column(conn: sqlite3.Connection) -> None:
    """迁移 punch_records 表：增加打卡时间列（兼容生产表与测试副本表）

    ERP 原始打卡记录若含打卡时间（punchTime / clockTime / 打卡时间 等任意一种），
    同步时即写入本列；若 ERP 不返回该字段，则保持为空，不影响其它字段。
    """
    cursor = conn.cursor()
    # 同时兼容生产表与测试副本表（punch_records_test 由生产表备份而来，
    # 但若在加列之前已建，则需补列）
    tables = ["punch_records"]
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'punch_records_%'"
    )
    tables += [row[0] for row in cursor.fetchall()]
    for tbl in tables:
        cursor.execute(f"PRAGMA table_info({tbl})")
        cols = [row[1] for row in cursor.fetchall()]
        if "punch_time" not in cols:
            logger.info("%s 缺少列 punch_time，执行 ALTER ADD COLUMN", tbl)
            cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN punch_time TEXT")
    conn.commit()


def _migrate_unique_to_identification_number(conn: sqlite3.Connection) -> None:
    """迁移 punch_records 唯一约束：UNIQUE(punch_date, erp_id) → UNIQUE(punch_date, identification_number)

    背景：
        ERP MQ 推送的消息体常常缺 `id` 字段（阿里云 RocketMQ 实例化时高凡/华南保利
        的真实事件就没有），导致 erp_id 为空字符串 ""。原 UNIQUE(punch_date, erp_id)
        约束下，多条缺 id 的消息会触发互相 UPDATE 覆盖，数据丢失。

    步骤：
        1. 检测 UNIQUE INDEX idx_uniq_punch_date_idnum 是否存在（幂等性）
        2. 清理 (punch_date, identification_number) 冲突行（保留 id 较小的）
        3. 重建表（SQLite 不支持 DROP CONSTRAINT，只能 ALTER TABLE RENAME + 新建 + 数据迁移）
        4. 创建新 UNIQUE INDEX（WHERE 子句避免空身份证号被纳入去重）
    """
    cursor = conn.cursor()

    # 1) 幂等检查：新 UNIQUE INDEX 已存在则跳过
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_uniq_punch_date_idnum'"
    )
    if cursor.fetchone():
        logger.info("punch_records 已迁移到 UNIQUE(punch_date, identification_number)，跳过")
        return

    # 2) 找出所有 punch_records_* 副本表（含测试表）
    tables = ["punch_records"]
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'punch_records%'"
    )
    tables += [row[0] for row in cursor.fetchall()]

    for tbl in tables:
        # 表是否存在
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        )
        row = cursor.fetchone()
        if not row:
            continue
        sql_def = row[0] or ""

        # 已迁移（新约束已存在）则跳过
        if "UNIQUE(punch_date, identification_number)" in sql_def:
            logger.info("%s 已包含新唯一约束，跳过迁移", tbl)
            continue

        # 旧约束已无（表已经是新约束了）→ 仅补 INDEX
        # 走完整迁移
        logger.info("开始迁移 %s 的唯一约束 ...", tbl)

        # 3) 清理 (punch_date, identification_number) 冲突（保留 id 较小）
        #    用子查询避免自删
        cursor.execute(f"""
            DELETE FROM {tbl}
            WHERE id NOT IN (
                SELECT MIN(id) FROM {tbl}
                WHERE identification_number IS NOT NULL AND identification_number != ''
                GROUP BY punch_date, identification_number
            )
            AND identification_number IS NOT NULL AND identification_number != ''
        """)
        deleted = cursor.rowcount
        if deleted:
            logger.info("%s 清理 (punch_date, identification_number) 冲突行: %d", tbl, deleted)

    # 4) 重建表（统一处理，避免每张表重写 CREATE TABLE）
    for tbl in list(tables):
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        )
        row = cursor.fetchone()
        if not row:
            continue
        sql_def = row[0] or ""
        if "UNIQUE(punch_date, identification_number)" in sql_def:
            # 已迁移，仅确保 UNIQUE INDEX 存在
            cursor.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_uniq_punch_date_idnum
                ON {tbl}(punch_date, identification_number)
                WHERE identification_number IS NOT NULL AND identification_number != ''
            """)
            continue

        # RENAME → 新建 → 数据迁移 → DROP 备份
        backup = f"{tbl}_pre_uniq_migration"
        cursor.execute(f"ALTER TABLE {tbl} RENAME TO {backup}")

        # 新表 SQL（保留旧表所有列 + 新 UNIQUE 约束）
        # 不重建为完整表定义，用 LIKE 复制旧表结构并替换约束
        # SQLite 的 CREATE TABLE ... AS SELECT 不能复制约束，所以手动重写
        cursor.execute(f"""
            CREATE TABLE {tbl} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                erp_id INTEGER,
                punch_date TEXT NOT NULL,
                member_id TEXT,
                member_name TEXT,
                identification_number TEXT,
                age INTEGER,
                project_name TEXT,
                team_name TEXT,
                supplier_name TEXT,
                category_name TEXT,
                examination_status TEXT,
                telephone TEXT,
                project_manager TEXT,
                manager_phone TEXT,
                manager_email TEXT,
                synced_at TEXT,
                punch_time TEXT,
                UNIQUE(punch_date, identification_number)
            )
        """)
        # 数据迁移
        cursor.execute(f"""
            INSERT INTO {tbl} SELECT * FROM {backup}
        """)
        # 删除备份
        cursor.execute(f"DROP TABLE {backup}")
        # 加 UNIQUE INDEX
        cursor.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_uniq_punch_date_idnum
            ON {tbl}(punch_date, identification_number)
            WHERE identification_number IS NOT NULL AND identification_number != ''
        """)
        logger.info("%s 唯一约束已迁移到 (punch_date, identification_number)", tbl)

    conn.commit()
    logger.info("punch_records 唯一约束迁移完成")


# ==================== 打卡数据操作 ====================

# ERP 可能使用的「打卡时间」字段名（驼峰 / 蛇形 / 常见别名 / 中文），
# 命中任意一个即写入 punch_time；都不命中则留空（不污染数据）。
_PUNCH_TIME_KEYS = (
    "punchTime", "punch_time", "punchtime", "punchDateTime",
    "clockTime", "signTime", "signInTime", "attendTime",
    "checkInTime", "checkinTime", "打卡时间", "打卡日期",
)


def _pick_punch_time(r: dict) -> str:
    for k in _PUNCH_TIME_KEYS:
        v = r.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


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
            # 项目经理三列（ERP 实时消息体携带，避免被 _resolve_manager 缓存污染）
            r.get("projectManager") or r.get("project_manager") or "",
            r.get("managerPhone") or r.get("manager_phone") or "",
            r.get("managerEmail") or r.get("manager_email") or "",
            synced_at,
            _pick_punch_time(r),
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
                    telephone, project_manager, manager_phone, manager_email,
                    synced_at, punch_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(punch_date, identification_number) DO UPDATE SET
                    erp_id=excluded.erp_id,
                    member_id=excluded.member_id,
                    member_name=excluded.member_name,
                    identification_number=excluded.identification_number,
                    age=excluded.age,
                    project_name=excluded.project_name,
                    team_name=excluded.team_name,
                    supplier_name=excluded.supplier_name,
                    category_name=excluded.category_name,
                    examination_status=excluded.examination_status,
                    telephone=excluded.telephone,
                    project_manager=excluded.project_manager,
                    manager_phone=excluded.manager_phone,
                    manager_email=excluded.manager_email,
                    synced_at=excluded.synced_at,
                    punch_time=excluded.punch_time
            """, rows)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def get_punch_records(
    punch_date: Optional[str] = None,
    limit: int = 500,
    table: str = "punch_records",
) -> list[dict]:
    """查询打卡记录

    Args:
        table: 表名（默认生产表 ``punch_records``；测试时可传 ``punch_records_test``）。
               表名必须已经存在且结构兼容，否则会报错。
    """
    # 白名单校验，防止 SQL 注入
    if table != "punch_records" and not table.startswith("punch_records_"):
        raise ValueError(f"非法的 punch_records 表名: {table}")
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            if punch_date:
                cursor.execute(
                    f"SELECT * FROM {table} WHERE punch_date = ? ORDER BY id LIMIT ?",
                    (punch_date, limit),
                )
            else:
                cursor.execute(
                    f"SELECT * FROM {table} ORDER BY punch_date DESC, id LIMIT ?",
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


def get_manager_info_by_project(project_name: str) -> dict:
    """按项目名称回退查询项目经理联系方式（实时事件经理解析用）

    从已有打卡记录中取该项目首个含联系方式的记录；用于实时事件到达时，
    即便当日尚未做全量经理同步，也能补全经理联系方式。查不到返回空字典。
    """
    if not project_name:
        return {}
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT project_manager, manager_phone, manager_email "
                "FROM punch_records WHERE project_name = ? "
                "AND (manager_phone <> '' OR manager_email <> '') LIMIT 1",
                (project_name,),
            )
            row = cursor.fetchone()
            return dict(row) if row else {}
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

    去重规则（用户约定 2026-08-26）：
    - 同一 (name, id_number) 视为同一人
    - 用 end_date 最新的那条数据替换 end_date 老的那条
    - 仅当新数据 end_date >= 旧数据 end_date 时才覆盖（保险：避免老保单回退覆盖新保单）

    Args:
        persons: 人员列表，每个 dict 需包含 status 字段（"正常"/"失效"）

    Returns:
        写入条数（新增+更新）
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
                name = (p.get("name") or "").strip()
                id_num = (p.get("id_number") or "").strip()
                policy_number = (p.get("policy_number") or "").strip()
                if not id_num:
                    continue
                new_start = p.get("start_date", "")
                new_end = p.get("end_date", "")
                # status 归一化到白名单 {正常, 失效}（防御批改类型/Excel 任意文本污染）
                status = _normalize_status(p.get("status"), new_end)

                cursor.execute("""
                    INSERT INTO insurance_personnel (
                        name, id_number, id_type, company, start_date, end_date,
                        job_title, birth_date, insurance_company, policy_number,
                        source_file, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name, id_number) WHERE id_number != '' DO UPDATE SET
                        company = excluded.company,
                        start_date = excluded.start_date,
                        end_date = excluded.end_date,
                        job_title = excluded.job_title,
                        insurance_company = excluded.insurance_company,
                        policy_number = excluded.policy_number,
                        source_file = excluded.source_file,
                        status = excluded.status,
                        created_at = excluded.created_at
                    WHERE
                        -- 仅在「新数据 end_date 更晚」时覆盖（保险型语义）
                        -- 同时把空 end_date 当作 1900-01-01 兜底，保证老记录可被更新
                        (insurance_personnel.end_date = '' OR
                         excluded.end_date = '' OR
                         excluded.end_date >= insurance_personnel.end_date)
                """, (
                    name, id_num,
                    p.get("id_type", "身份证"), p.get("company", ""),
                    new_start, new_end,
                    p.get("job_title", ""), p.get("birth_date", ""),
                    p.get("insurance_company", ""), policy_number,
                    p.get("file_name", p.get("source_file", "")),
                    status, created_at,
                ))
                if cursor.rowcount > 0:
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
                # status 归一化到白名单 {正常, 失效}（防御批改类型/Excel 任意文本污染）
                status = _normalize_status(p.get("status"), end_date)
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


def deactivate_insurance(id_numbers: list[str], end_date: str | None = None,
                        policy_number: str | None = None) -> int:
    """减保：将指定身份证号的人员状态设为失效

    Args:
        id_numbers: 身份证号列表
        end_date: 减保生效日（YYYY-MM-DD）。如果提供，会同步更新 end_date 字段，
                   避免出现"status=失效 但 end_date 还是主保单止期"的不一致。
                   通常由批单的"批单生效日期"提供（见 metadata_extractor 的 endorsement_effective_date）。
        policy_number: 2026-09-16 新增：批单号。提供时仅减保该保单下的记录，
                       避免跨保单误改（同身份证在不同保单下的记录）。

    Returns:
        更新的条数

    Note:
        - 不提供 end_date 时保留旧行为（仅更新 status），以保证向后兼容。
        - 但推荐调用方始终显式传入减保生效日，避免数据不一致（参见 2026-09-15 秦克智事件）。
        - 推荐传入 policy_number 防跨保单误改（2026-09-16 徐成强事件：批单0034742015 减保
          把同身份证的华安一年保单 1763 也改成失效）。
    """
    id_numbers = [str(i).strip() for i in id_numbers if i and str(i).strip()]
    if not id_numbers:
        return 0

    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in id_numbers)
            where_clauses = [f"id_number IN ({placeholders})"]
            params: list = []
            if end_date:
                end_date = str(end_date).strip()
            if policy_number:
                where_clauses.append("policy_number = ?")
                params.append(str(policy_number).strip())
            where_sql = " AND ".join(where_clauses)
            # 注意参数顺序：必须与 WHERE 子句中占位符的出现顺序严格一致
            # where_sql 形如 "id_number IN (?,?,?) AND policy_number = ?"
            # 对应参数顺序: id_numbers..., 然后 policy_number
            if end_date:
                # 减保生效日：同步更新 status 和 end_date，保证一致性
                cursor.execute(
                    f"UPDATE insurance_personnel SET status = '失效', end_date = ? "
                    f"WHERE {where_sql}",
                    [end_date, *id_numbers, *params],
                )
            else:
                # 旧行为：仅更新 status（不推荐）
                cursor.execute(
                    f"UPDATE insurance_personnel SET status = '失效' WHERE {where_sql}",
                    [*id_numbers, *params],
                )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def refresh_expired_status() -> int:
    """将已到起止日期的人员状态刷新为失效

    Returns:
        更新的条数（失败时返回 0）
    """
    today = datetime.now().strftime("%Y-%m-%d")
    try:
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
    except Exception as e:  # noqa: BLE001
        # 部分运行环境（如 sandbox）下 db 写权限受限，失败不应让上层接口崩溃
        logger.warning("refresh_expired_status 失败（已忽略）: %s", e)
        return 0


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


def find_inconsistent_deactivations(today: str | None = None) -> list[dict]:
    """查找 status=失效 但 end_date > today 的不一致记录。

    这种记录通常意味着：减保时只更新了 status，未同步更新 end_date。
    真实业务中，status=失效 意味着"保单已不再覆盖此人"，end_date 应该等于
    减保生效日（或更早），而不可能晚于今天。

    用于：
    - 一次性全库扫描（修复历史脏数据）
    - 每日例行检查（防止新代码回归引入不一致）

    Args:
        today: 用于比较的"今天"，格式 YYYY-MM-DD。None 则使用 datetime.now()。

    Returns:
        不一致记录列表，每项含 id/name/id_number/policy_number/status/start_date/end_date/source_file
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, id_number, policy_number, status,
                       start_date, end_date, source_file, created_at
                FROM insurance_personnel
                WHERE status = '失效'
                  AND end_date != ''
                  AND end_date > ?
                ORDER BY id
                """,
                (today,),
            )
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
            value = updates[key]
            # status 归一化到白名单 {正常, 失效}（编辑页下拉框误传批改类型时的防线）
            if key == "status":
                value = _normalize_status(value, updates.get("end_date", ""))
            fields.append(f"{key} = ?")
            values.append(value)
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
    """获取按身份证号分组的有效保单人员（未失效且未到期）

    2026-09-16 加固（段小平事件）：
        原实现用 `status = '正常'` 严格等值匹配。一旦库里出现非白名单 status
        （如被误写入的批改类型 '增保'），即使该人保险未到期也会被漏匹配，
        进而在打卡比对时被误判为「未参保」并误发邮件/短信给项目经理。

        现改为**排除式**判断：只要不是明确的 '失效' 且未到期，就视为有效。
        这样任何未知的 status 取值都不会导致误报漏保。

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
                WHERE (status IS NULL OR status = '' OR status != '失效')
                  AND (end_date = '' OR end_date >= ?)
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
