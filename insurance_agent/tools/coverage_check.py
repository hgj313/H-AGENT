"""打卡数据同步 + 保险覆盖检查

功能：
1. sync_punch_data() — 从 ERP 拉取今日打卡数据，写入数据库
2. check_insurance_coverage() — 对比打卡人员 vs 保单人员，找出：
   - 打了卡但没有保险（无保单记录）
   - 打了卡但保险已过期
   对上述情况触发邮件提醒。

独立可测，不依赖 Agent 框架。
"""

import logging
from datetime import datetime

from insurance_agent.infrastructure import database as db
from insurance_agent.infrastructure.erp_client import ERPClient

logger = logging.getLogger(__name__)


def sync_punch_data(session_manager, punch_date: str = None) -> dict:
    """从 ERP 同步打卡数据到数据库

    Args:
        session_manager: SessionManager 实例
        punch_date: 打卡日期（默认今天）

    Returns:
        {"success", "punch_date", "total", "stored", "error"}
    """
    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")

    client = ERPClient(session_manager)
    result = client.fetch_all_punch_data(punch_date)

    if not result.get("success"):
        return {
            "success": False,
            "punch_date": punch_date,
            "total": 0,
            "stored": 0,
            "error": result.get("error", "同步失败"),
        }

    records = result.get("records", [])
    # 清空当天旧数据，重新写入
    db.clear_punch_records(punch_date)
    stored = db.upsert_punch_records(records, punch_date)

    logger.info("打卡数据同步完成: %s 共 %d 条，入库 %d 条", punch_date, len(records), stored)

    return {
        "success": True,
        "punch_date": punch_date,
        "total": len(records),
        "stored": stored,
    }


def check_insurance_coverage(punch_date: str = None) -> dict:
    """检查打卡人员是否有正常状态的保单

    简化逻辑：
    - 取当天打卡人员（按身份证号去重）
    - 到保单人员数据中查询其是否有「状态为正常」的保单
    - 有正常保单 → 覆盖正常
    - 没有正常保单 → 归入待提醒名单（提醒购买保险）

    Returns:
        {
            "success", "punch_date",
            "total_punch", "covered", "uninsured",
            "uninsured_list": [...],   # 无正常状态保单的人员
        }
    """
    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")

    # 先刷新到期状态：已到起止日期的自动标记为失效
    db.refresh_expired_status()

    punch_records = db.get_punch_records(punch_date, limit=10000)

    # 按身份证号去重（同一个人可能多条打卡记录）
    seen = {}
    for r in punch_records:
        id_num = r.get("identification_number", "")
        if id_num and id_num not in seen:
            seen[id_num] = r

    # 有效保单（状态为正常）
    active_insurance = db.get_active_insurance_by_id()

    # 无正常状态保单的人员
    uninsured_list = []
    for id_num, record in seen.items():
        if active_insurance.get(id_num):
            continue  # 有正常状态保单，覆盖正常
        uninsured_list.append({
            "name": record.get("member_name", ""),
            "id_number": id_num,
            "project_name": record.get("project_name", ""),
            "team_name": record.get("team_name", ""),
            "supplier_name": record.get("supplier_name", ""),
            "category_name": record.get("category_name", ""),
        })

    return {
        "success": True,
        "punch_date": punch_date,
        "total_punch": len(seen),
        "covered": len(seen) - len(uninsured_list),
        "uninsured": len(uninsured_list),
        "uninsured_list": uninsured_list,
    }
