"""打卡数据 → 飞书多维表格 同步器

职责
----
把本地 `punch_records` 表里的每日打卡数据，同步到飞书多维表格。

数据源
------
**唯一数据源 = 本地 `punch_records` 表**，不重复调用 ERP 接口。
理由：
1. `punch_records` 已经过 ERP 拉取 + 按 (punch_date, identification_number) 去重 + 项目经理信息补全；
2. 实时链路（MQ）也会写入同一张表 → 全量与实时两条路径的成果天然汇合；
3. 避免同一份数据两个来源导致的不一致。

幂等设计
--------
业务主键 = **(打卡日期, 身份证号)**。
飞书侧通过「记录映射表」`feishu_punch_sync_map` 保存 (punch_date, id_number) → record_id 的对应关系：
- 本地有映射 → 走 `batch_update`（幂等，重复同步不会产生重复行）
- 本地无映射 → 走 `batch_create`，成功后回写映射

这样即使一天内多次同步、或服务重启重跑，也不会在飞书表里堆重复记录。

字段映射
--------
默认映射见 `DEFAULT_FIELD_MAPPING`，可通过配置文件 `field_mapping` 覆盖
（键 = 飞书列名，值 = 本地 punch_records 字段名）。
未在映射中出现的列不会被写入。

关键类型转换
------------
- 日期/日期时间列 → 13 位毫秒时间戳（int）。飞书不接受字符串日期。
- 数字列 → int/float；空值传 None 而不是 ""。
- 单选列 → 必须传已存在的选项名；本地没有对应列时直接跳过该字段（交由配置决定）。
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from insurance_agent.infrastructure import database as db
from insurance_agent.infrastructure.feishu_bitable_client import (
    FeishuBitableClient,
    FeishuBitableError,
    load_client_from_config,
)
from insurance_agent.infrastructure.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

# 配置文件路径（与既有 .feishu_webhook.json 风格一致，独立配置不互相影响）
CONFIG_PATH = os.path.join(PROJECT_ROOT, ".feishu_bitable.json")

# 同步状态表（本地维护 打卡日期+身份证号 → 飞书 record_id 的映射）
SYNC_MAP_TABLE = "feishu_punch_sync_map"

# 默认字段映射：飞书列名 → 本地 punch_records 字段名
DEFAULT_FIELD_MAPPING = {
    "姓名": "member_name",
    "身份证号": "identification_number",
    "项目名称": "project_name",
    "班组": "team_name",
    "劳务公司": "supplier_name",
    "劳务分类": "category_name",
    "审核状态": "examination_status",
    "年龄": "age",
    "电话": "telephone",
    "项目经理": "project_manager",
    "项目经理手机": "manager_phone",
    "项目经理邮箱": "manager_email",
    "打卡日期": "punch_date",
    "打卡时间": "punch_time",
}

# 日期型列（需要转毫秒时间戳）
_DATE_FIELDS = {"打卡日期", "打卡时间", "日期", "时间"}

# 数字型列（需要转 int）
_NUMBER_FIELDS = {"年龄", "工龄"}

# 时间字符串 → 毫秒时间戳
_TIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
]


def to_millis(raw) -> Optional[int]:
    """把日期/时间字符串转成 13 位毫秒时间戳

    飞书日期字段只认毫秒时间戳，传字符串会报 1254064。
    无法解析时返回 None（该字段不写入，而不是写脏值）。
    """
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        # 已是数字：10 位秒 → 13 位毫秒
        val = int(raw)
        return val * 1000 if val < 10_000_000_000 else val

    s = str(raw).strip()
    if not s:
        return None
    # 纯数字时间戳
    if s.isdigit() and len(s) in (10, 13):
        val = int(s)
        return val * 1000 if len(s) == 10 else val

    for fmt in _TIME_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue

    try:
        iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        logger.debug("无法解析时间为时间戳: %r", raw)
        return None


def to_number(raw) -> Optional[float]:
    """把字符串数字转成数字；空值/非法值返回 None"""
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        return None  # 飞书数字字段不接受布尔
    if isinstance(raw, (int, float)):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    try:
        val = float(s)
        return int(val) if val.is_integer() else val
    except ValueError:
        return None


def build_fields(record: dict, mapping: Dict[str, str]) -> dict:
    """把一条本地打卡记录转成飞书 fields 字典

    只写入 mapping 里声明的列；值按列名语义做类型转换；
    转换后为 None 的字段直接跳过（避免用空串污染飞书列）。
    """
    fields: dict = {}
    for feishu_col, local_key in mapping.items():
        raw = record.get(local_key)
        if raw in (None, ""):
            continue
        if feishu_col in _DATE_FIELDS:
            ms = to_millis(raw)
            if ms is not None:
                fields[feishu_col] = ms
        elif feishu_col in _NUMBER_FIELDS:
            num = to_number(raw)
            if num is not None:
                fields[feishu_col] = num
        else:
            fields[feishu_col] = str(raw)
    return fields


class PunchBitableSync:
    """打卡数据同步到飞书多维表格

    用法::

        sync = PunchBitableSync()
        result = sync.sync_date("2026-11-10")
        # {"success": True, "created": 449, "updated": 0, "skipped": 0, "failed": 0}
    """

    def __init__(self, config_path: str = CONFIG_PATH, client: Optional[FeishuBitableClient] = None):
        self._config_path = config_path
        self._config = self._load_config(config_path)
        self._client = client
        self._mapping = self._config.get("field_mapping") or DEFAULT_FIELD_MAPPING

    # ==================== 配置 ====================

    @staticmethod
    def _load_config(path: str) -> dict:
        """加载配置；文件不存在或格式错误时返回禁用状态配置"""
        if not os.path.exists(path):
            logger.info("飞书多维表格同步配置不存在: %s（同步功能视为关闭）", path)
            return {"enabled": False}
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg if isinstance(cfg, dict) else {"enabled": False}
        except Exception as e:
            logger.error("加载飞书多维表格配置失败: %s", e)
            return {"enabled": False}

    def reload_config(self) -> dict:
        """热加载配置（改完 .feishu_bitable.json 无需重启服务）"""
        self._config = self._load_config(self._config_path)
        self._mapping = self._config.get("field_mapping") or DEFAULT_FIELD_MAPPING
        logger.info("飞书多维表格同步配置已重载: enabled=%s", self._config.get("enabled"))
        return self._config

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled")) and bool(self._config.get("app_id")) \
            and bool(self._config.get("app_secret")) and bool(self._config.get("app_token"))

    def get_client(self) -> FeishuBitableClient:
        """获取（或懒加载）API 客户端"""
        if self._client is None:
            self._client = load_client_from_config(self._config)
        return self._client

    # ==================== 同步主流程 ====================

    def sync_date(self, punch_date: str = None) -> dict:
        """把某一天的打卡数据同步到飞书多维表格

        Args:
            punch_date: YYYY-MM-DD，默认今天

        Returns:
            {"success", "punch_date", "total", "created", "updated", "skipped", "failed", "error"}
        """
        punch_date = punch_date or datetime.now().strftime("%Y-%m-%d")

        if not self.enabled:
            return {
                "success": False,
                "disabled": True,
                "punch_date": punch_date,
                "total": 0,
                "error": "飞书多维表格同步未启用（检查 .feishu_bitable.json 的 enabled 与凭证配置）",
            }

        records = db.get_punch_records(punch_date=punch_date, limit=100000)
        if not records:
            return {
                "success": True,
                "punch_date": punch_date,
                "total": 0,
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "failed": 0,
                "error": "本地无该日打卡数据",
            }

        client = self.get_client()
        try:
            table_id = client.resolve_table_id(self._config.get("table_name", ""))
        except ValueError as e:
            return {
                "success": False,
                "punch_date": punch_date,
                "total": len(records),
                "error": str(e),
            }

        # 已有映射：本地主键 → 飞书 record_id
        existing_map = self._load_sync_map(punch_date)

        to_create: List[dict] = []
        to_update: List[dict] = []
        create_keys: List[tuple] = []  # 与 to_create 同序，回写映射用
        skipped = 0

        for rec in records:
            id_num = (rec.get("identification_number") or "").strip()
            if not id_num:
                skipped += 1
                continue
            fields = build_fields(rec, self._mapping)
            if not fields:
                skipped += 1
                continue
            record_id = existing_map.get(id_num)
            if record_id:
                to_update.append({"record_id": record_id, "fields": fields})
            else:
                to_create.append({"fields": fields})
                create_keys.append((id_num, fields))

        created_n = 0
        updated_n = 0
        failed = 0
        errors = []

        # 更新（已有 record_id）
        if to_update:
            try:
                updated_n = len(client.batch_update(to_update, table_id=table_id))
            except FeishuBitableError as e:
                failed += len(to_update)
                errors.append(f"批量更新失败: {e}")
                logger.error("飞书批量更新失败: %s", e)

        # 新增 + 回写映射
        if to_create:
            try:
                new_records = client.batch_create(to_create, table_id=table_id)
                created_n = len(new_records)
                # 按返回顺序回写映射（batch_create 保证 records 与返回值同序）
                for (id_num, _fields), new_rec in zip(create_keys, new_records):
                    rid = new_rec.get("record_id")
                    if rid:
                        self._save_sync_map(punch_date, id_num, rid)
            except FeishuBitableError as e:
                failed += len(to_create)
                errors.append(f"批量新增失败: {e}")
                logger.error("飞书批量新增失败: %s", e)

        result = {
            "success": failed == 0,
            "punch_date": punch_date,
            "total": len(records),
            "created": created_n,
            "updated": updated_n,
            "skipped": skipped,
            "failed": failed,
        }
        if errors:
            result["error"] = "; ".join(errors)
        logger.info(
            "飞书多维表格同步完成: %s 共 %d 条 → 新增 %d / 更新 %d / 跳过 %d / 失败 %d",
            punch_date, len(records), created_n, updated_n, skipped, failed,
        )
        return result

    def probe(self) -> dict:
        """连通性自检：验 token + 列表结构 + 取字段名

        用于部署后快速确认配置是否正确（不写任何数据）。
        """
        if not self.enabled:
            return {"success": False, "error": "同步未启用"}

        client = self.get_client()
        out = {"success": True}
        try:
            tables = client.list_tables()
            out["tables"] = [{"table_id": t.get("table_id"), "name": t.get("name")} for t in tables]
            table_id = client.resolve_table_id(self._config.get("table_name", ""))
            out["table_id"] = table_id
            fields = client.list_fields(table_id)
            out["fields"] = [f.get("field_name") for f in fields]
            out["missing_columns"] = [
                col for col in self._mapping if col not in out["fields"]
            ]
            out["token_ok"] = True
        except FeishuBitableError as e:
            out = {"success": False, "error": str(e)}
        return out

    # ==================== 同步映射表 ====================

    @staticmethod
    def _ensure_sync_map_table() -> None:
        """确保同步映射表存在（幂等）"""
        with db._lock:
            conn = db.get_connection()
            try:
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {SYNC_MAP_TABLE} (
                        punch_date TEXT NOT NULL,
                        id_number TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        synced_at TEXT,
                        PRIMARY KEY (punch_date, id_number)
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    def _load_sync_map(self, punch_date: str) -> Dict[str, str]:
        """读某天的映射：{id_number: record_id}"""
        self._ensure_sync_map_table()
        with db._lock:
            conn = db.get_connection()
            try:
                rows = conn.execute(
                    f"SELECT id_number, record_id FROM {SYNC_MAP_TABLE} WHERE punch_date = ?",
                    (punch_date,),
                ).fetchall()
                return {r[0]: r[1] for r in rows}
            finally:
                conn.close()

    def _save_sync_map(self, punch_date: str, id_number: str, record_id: str) -> None:
        """写入/更新映射（幂等）"""
        self._ensure_sync_map_table()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with db._lock:
            conn = db.get_connection()
            try:
                conn.execute(
                    f"""INSERT INTO {SYNC_MAP_TABLE} (punch_date, id_number, record_id, synced_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(punch_date, id_number) DO UPDATE SET
                            record_id=excluded.record_id, synced_at=excluded.synced_at""",
                    (punch_date, id_number, record_id, now),
                )
                conn.commit()
            finally:
                conn.close()
