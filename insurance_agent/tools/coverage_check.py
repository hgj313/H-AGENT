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
    """检查打卡人员的保险覆盖情况

    对比逻辑：
    - 取当天打卡记录（按身份证号去重）
    - 取有效保单人员（未过期，按身份证号分组）
    - 对每个打卡人员判断：
        1. 无任何保单记录 → "无保险"
        2. 有保单记录但全部已过期 → "保险已过期"
        3. 有有效保单 → 正常

    Returns:
        {
            "success", "punch_date",
            "total_punch", "covered", "uninsured", "expired",
            "uninsured_list": [...],   # 无保险人员
            "expired_list": [...],     # 已过期人员
        }
    """
    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")

    punch_records = db.get_punch_records(punch_date, limit=10000)
    if not punch_records:
        return {
            "success": True,
            "punch_date": punch_date,
            "total_punch": 0,
            "covered": 0,
            "uninsured": 0,
            "expired": 0,
            "uninsured_list": [],
            "expired_list": [],
        }

    # 按身份证号去重（同一个人可能多条打卡记录）
    seen = {}
    for r in punch_records:
        id_num = r.get("identification_number", "")
        if id_num and id_num not in seen:
            seen[id_num] = r

    # 有效保单（未过期）
    active_insurance = db.get_active_insurance_by_id()

    # 全部保单（含过期，用于判断"有过保单但已过期"）
    all_insurance = {}
    for p in db.get_insurance_personnel():
        id_num = p.get("id_number", "")
        if id_num:
            all_insurance.setdefault(id_num, []).append(p)

    uninsured_list = []  # 无保险
    expired_list = []    # 保险已过期

    for id_num, record in seen.items():
        person_active = active_insurance.get(id_num, [])
        person_all = all_insurance.get(id_num, [])

        base_info = {
            "name": record.get("member_name", ""),
            "id_number": id_num,
            "project_name": record.get("project_name", ""),
            "team_name": record.get("team_name", ""),
            "supplier_name": record.get("supplier_name", ""),
            "category_name": record.get("category_name", ""),
        }

        if person_active:
            # 有有效保单 → 正常
            continue
        elif person_all:
            # 有保单但全部已过期
            latest_end = max((p.get("end_date", "") for p in person_all), default="")
            base_info["last_end_date"] = latest_end
            base_info["insurance_company"] = person_all[0].get("insurance_company", "")
            expired_list.append(base_info)
        else:
            # 完全无保单
            uninsured_list.append(base_info)

    return {
        "success": True,
        "punch_date": punch_date,
        "total_punch": len(seen),
        "covered": len(seen) - len(uninsured_list) - len(expired_list),
        "uninsured": len(uninsured_list),
        "expired": len(expired_list),
        "uninsured_list": uninsured_list,
        "expired_list": expired_list,
    }
