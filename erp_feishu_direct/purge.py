"""历史行清理：把「打卡日期」早于指定日期的行从飞书表里删掉

为什么必须有
------------
1. 表名是「今日打卡数据」，语义上就该只装当天数据；
2. **幂等映射只保留 7 天**（``sync.map_keep_days``）。超过 7 天后，
   同一个人在第 8 天再打卡 → 映射查不到 → 走 ``batch_create`` 建新行，
   而他第 1 天那行还躺在表里 → 同一人两行、且永远无法自愈。
   所以「清历史」不是洁癖，是幂等机制能闭环的前提。

删除是破坏性操作，因此：
- 默认只删「打卡日期」**严格早于**今天零点 的行，当天的行一律不碰；
- 日期为空的行**不删**（可能是手工加的记录），只统计并告警；
- 每次删除都写日志（删了多少条、覆盖哪些日期）。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("erp_feishu_direct.purge")

# 目标表里承载日期的列名
DATE_COLUMN = "打卡日期"

# 单次拉取上限（防止表异常膨胀时把内存打爆）
_MAX_PULL = 50000


def _record_date_ms(fields: Dict[str, Any]) -> Optional[int]:
    """取一条记录的打卡日期毫秒时间戳；取不到返回 None"""
    raw = (fields or {}).get(DATE_COLUMN)
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        val = int(raw)
        return val * 1000 if val < 10_000_000_000 else val
    s = str(raw).strip()
    if s.isdigit() and len(s) in (10, 13):
        val = int(s)
        return val * 1000 if len(s) == 10 else val
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(s, fmt).timestamp() * 1000)
        except ValueError:
            continue
    return None


def cutoff_millis(keep_days: int = 0) -> int:
    """返回「保留边界」毫秒时间戳。

    keep_days=0 → 边界 = 今天零点（只保留今天）
    keep_days=N  → 边界 = (今天 - N 天) 零点（保留今天与前 N 天）
    """
    dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if keep_days > 0:
        dt = dt - timedelta(days=keep_days)
    return int(dt.timestamp() * 1000)


def purge_history(
    client,
    table_id: str,
    keep_days: int = 0,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """删除打卡日期早于保留边界的行。

    Args:
        client: FeishuBitableClient
        table_id: 目标表
        keep_days: 保留天数，0 = 只保留今天
        dry_run: True 时只统计不删

    Returns:
        {"total", "deleted", "skipped_no_date", "dry_run", "cutoff_date", "dates": {...}}
    """
    boundary = cutoff_millis(keep_days)
    cutoff_date = datetime.fromtimestamp(boundary / 1000).strftime("%Y-%m-%d")

    records = client.list_records(table_id=table_id, page_size=500, max_records=_MAX_PULL)

    stale_ids: List[str] = []
    no_date = 0
    date_hist: Dict[str, int] = {}

    for rec in records:
        fields = rec.get("fields") or {}
        ms = _record_date_ms(fields)
        if ms is None:
            no_date += 1
            continue
        day = datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")
        date_hist[day] = date_hist.get(day, 0) + 1
        if ms < boundary:
            stale_ids.append(rec["record_id"])

    result = {
        "total": len(records),
        "deleted": 0,
        "stale": len(stale_ids),
        "skipped_no_date": no_date,
        "dry_run": bool(dry_run),
        "cutoff_date": cutoff_date,
        "dates": date_hist,
    }

    if not stale_ids:
        logger.info("历史清理：无需删除（边界 %s 之前无记录）", cutoff_date)
        return result

    if dry_run:
        logger.info("历史清理[试运行]：边界 %s 之前共 %d 条，将删除",
                    cutoff_date, len(stale_ids))
        return result

    deleted = client.batch_delete(stale_ids, table_id=table_id)
    result["deleted"] = deleted
    logger.warning("历史清理：已删除 %d 条「打卡日期」早于 %s 的记录（表内原有分布 %s）",
                   deleted, cutoff_date, date_hist)
    return result
