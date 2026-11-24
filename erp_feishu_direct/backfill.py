"""历史打卡数据回补：从本地 SQLite ``punch_records`` 补写飞书「今日打卡数据」表

为什么需要
----------
RocketMQ **无法回溯历史消息**。新的消费组只能从「订阅那一刻」开始收，
今天已经被 ``insurance-automation`` 组消费掉的 ~1900 条消息，
直连消费者永远拿不到。

而这些数据并没有丢 —— 它们已经在 8765 的本地 SQLite ``data/app.db``
的 ``punch_records`` 表里了（MQ 桥接的另一条链路一直在写）。
本工具把当天（或指定日期）的存量数据读出来，走**与实时链路完全相同**的
mapper + writer + 幂等映射写进飞书表。

关键设计
--------
* 复用 ``feishu_direct_sync_map.json`` 这同一份幂等映射 → 回补的行与之后
  实时推送的行**共享同一个 record_id**，不会变成两行。
* 幂等键 = 打卡日期 + 身份证号，与实时链路一致。
* 默认试运行（``--apply`` 才真正写）。

用法::

    H-AGENT\\.venv\\Scripts\\python.exe -m erp_feishu_direct.backfill            # 试运行
    H-AGENT\\.venv\\Scripts\\python.exe -m erp_feishu_direct.backfill --apply    # 实际写入
    H-AGENT\\.venv\\Scripts\\python.exe -m erp_feishu_direct.backfill --date 2026-11-23 --apply
"""

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime
from typing import Any, Dict, List

from erp_feishu_direct.config import (
    DLQ_PATH,
    SYNC_MAP_PATH,
    load_config,
    missing_keys,
)
from erp_feishu_direct.mapper import build_fields, extract_punch_date
from erp_feishu_direct.store import SyncMapStore
from erp_feishu_direct.writer import FeishuWriter

from insurance_agent.infrastructure.feishu_bitable_client import load_client_from_config

logger = logging.getLogger("erp_feishu_direct.backfill")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "app.db")

# SQLite 列名 → ERP 标准字段名（与 mapper.DEFAULT_FIELD_MAPPING 的键对应）
SQLITE_FIELD_MAP = {
    "member_name": "memberName",
    "identification_number": "identificationNumber",
    "project_name": "projectName",
    "team_name": "teamName",
    "supplier_name": "supplierName",
    "category_name": "categoryName",
    "examination_status": "examinationStatusName",
    "telephone": "telephone",
    "project_manager": "projectManager",
    "manager_phone": "managerPhone",
    "manager_email": "managerEmail",
    "punch_date": "punchDate",
    "punch_time": "punchTime",
}


def load_records(punch_date: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """从 SQLite 读某天的打卡记录，转成 ERP 标准事件"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"找不到 SQLite：{db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM punch_records WHERE punch_date = ?", (punch_date,)
        ).fetchall()
    finally:
        conn.close()

    events: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        ev: Dict[str, Any] = {}
        for col, key in SQLITE_FIELD_MAP.items():
            val = rec.get(col)
            if val is None:
                continue
            ev[key] = val
        if ev.get("identificationNumber"):
            events.append(ev)
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description="历史打卡数据回补到飞书「今日打卡数据」表")
    ap.add_argument("--date", default="", help="回补日期 YYYY-MM-DD，默认今天")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认试运行）")
    ap.add_argument("--db", default=DB_PATH, help="SQLite 路径")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    punch_date = args.date or datetime.now().strftime("%Y-%m-%d")

    cfg = load_config()
    missing = missing_keys(cfg)
    if missing:
        logger.error("缺少必要凭证: %s", ", ".join(missing))
        return 1

    try:
        events = load_records(punch_date, args.db)
    except FileNotFoundError as e:
        logger.error("%s", e)
        return 1

    print(f"日期 {punch_date}：本地读到 {len(events)} 条打卡记录")
    if not events:
        print("没有可回补的数据。")
        return 0

    # 预览前 3 条的产出
    for ev in events[:3]:
        print(f"  样例 → {build_fields(ev)}")

    if not args.apply:
        print(f"\n（试运行，未写入。加 --apply 执行）预计写入 {len(events)} 条")
        return 0

    fs = cfg["feishu"]
    client = load_client_from_config(fs)
    store = SyncMapStore(SYNC_MAP_PATH, keep_days=int(cfg.get("sync", {}).get("map_keep_days", 7)))
    writer = FeishuWriter(
        client=client,
        store=store,
        field_mapping=(fs.get("field_mapping") or None),
        table_id=fs.get("table_id", ""),
        max_batch_size=int(cfg.get("batch", {}).get("max_batch_size", 500)),
        retry=int(cfg.get("sync", {}).get("retry", 3)),
        retry_backoff=float(cfg.get("sync", {}).get("retry_backoff", 2.0)),
        dlq_path=DLQ_PATH,
    )

    # 分批写（每批 500 条，和实时链路同一个 writer）
    total = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    batch_size = int(cfg.get("batch", {}).get("max_batch_size", 500))
    for i in range(0, len(events), batch_size):
        chunk = events[i : i + batch_size]
        res = writer.write_batch(chunk)
        for k in total:
            total[k] += res.get(k, 0)
        logger.info("回补进度 %d/%d → %s", min(i + batch_size, len(events)), len(events), res)

    print(f"\n回补完成：新增 {total['created']} / 更新 {total['updated']} / "
          f"跳过 {total['skipped']} / 失败 {total['failed']}")
    print(f"幂等映射：{SYNC_MAP_PATH}")
    return 0 if total["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
