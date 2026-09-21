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
from concurrent.futures import ThreadPoolExecutor
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
    # 三个独立 ERP 接口（项目台账/人员列表/打卡数据）并发拉取，节省 ~50% 等待时间
    # 单 ERP 接口耗时：~3-8s/页；并发后总耗时 = max(三个) 而非 sum(三个)
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_punch = pool.submit(client.fetch_all_punch_data, punch_date)
        fut_projects = pool.submit(client.fetch_project_orders)
        fut_users = pool.submit(client.fetch_user_list)
        result = fut_punch.result()

    if not result.get("success"):
        return {
            "success": False,
            "punch_date": punch_date,
            "total": 0,
            "stored": 0,
            "error": result.get("error", "同步失败"),
        }

    records = result.get("records", [])
    # 清空当天旧数据，重新写入（单事务 executemany，< 0.1s）
    db.clear_punch_records(punch_date)
    stored = db.upsert_punch_records(records, punch_date)

    logger.info("打卡数据同步完成: %s 共 %d 条，入库 %d 条", punch_date, len(records), stored)

    # 同步项目经理信息：复用上面已并发拉取的 projects/users 数据，避免重复 HTTP 请求
    # 串行 → 节省 2 次 ERP 请求（项目台账 + 人员列表，共 ~15-20s）
    manager_synced = _sync_manager_info(
        session_manager, punch_date,
        prefetched_projects=fut_projects.result(),
        prefetched_users=fut_users.result(),
    )

    return {
        "success": True,
        "punch_date": punch_date,
        "total": len(records),
        "stored": stored,
        "manager_synced": manager_synced,
    }


def _sync_manager_info(
    session_manager,
    punch_date: str,
    prefetched_projects: dict = None,
    prefetched_users: dict = None,
) -> dict:
    """拉取项目台账 + 人员信息，构建项目经理映射并写入当天打卡记录

    Args:
        prefetched_projects: 已拉取的项目台账数据（来自 sync_punch_data 并发池），可避免重复请求
        prefetched_users: 已拉取的人员列表数据（同上）

    返回同步统计 {"success", "projects", "updated", "error"}
    """
    try:
        client = ERPClient(session_manager)
        manager_map = build_manager_map(
            client,
            prefetched_projects=prefetched_projects,
            prefetched_users=prefetched_users,
        )
        if not manager_map:
            return {"success": False, "projects": 0, "updated": 0, "error": "未获取到项目台账/人员信息"}
        updated = db.update_punch_manager_info(punch_date, manager_map)
        logger.info("项目经理信息同步完成: %d 个项目，更新 %d 条打卡记录", len(manager_map), updated)
        return {"success": True, "projects": len(manager_map), "updated": updated}
    except Exception as e:  # noqa: BLE001
        logger.warning("项目经理信息同步失败: %s", e)
        return {"success": False, "projects": 0, "updated": 0, "error": str(e)}


def build_manager_map(
    client,
    prefetched_projects: dict = None,
    prefetched_users: dict = None,
) -> dict:
    """从 ERP 构建 {项目名称: {project_manager, manager_phone, manager_email}} 映射

    数据来源：
    - 项目台账接口：projectName → projectDutyUserName（项目经理）
    - 人员信息接口：按 userId / name 匹配 → phone / email

    支持传入 prefetched_projects/prefetched_users 复用并发池中已拉取的数据，
    避免重复请求 ERP 接口（节省 ~15-20s）。
    """
    po = prefetched_projects if prefetched_projects is not None else client.fetch_project_orders()
    ul = prefetched_users if prefetched_users is not None else client.fetch_user_list()
    if not po.get("success") or not ul.get("success"):
        logger.warning(
            "拉取项目/人员信息失败: project=%s user=%s",
            po.get("error"), ul.get("error"),
        )
        return {}

    users_by_id = {u.get("id"): u for u in ul.get("records", [])}
    users_by_name = {}
    for u in ul.get("records", []):
        users_by_name.setdefault(u.get("name"), u)

    manager_map = {}
    for p in po.get("records", []):
        project_name = p.get("projectName", "")
        if not project_name:
            continue
        manager_name = p.get("projectDutyUserName") or p.get("projectAssignUserName") or ""
        manager_id = p.get("projectDutyUserId")
        user = users_by_id.get(manager_id) or users_by_name.get(manager_name)
        manager_map[project_name] = {
            "project_manager": manager_name,
            "manager_phone": (user or {}).get("phone", "") or "",
            "manager_email": (user or {}).get("email", "") or "",
        }
    return manager_map


def check_insurance_coverage(punch_date: str = None, punch_table: str = "punch_records") -> dict:
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

    punch_records = db.get_punch_records(punch_date, limit=10000, table=punch_table)

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
            "project_manager": record.get("project_manager", ""),
            "manager_phone": record.get("manager_phone", ""),
            "manager_email": record.get("manager_email", ""),
        })

    return {
        "success": True,
        "punch_date": punch_date,
        "total_punch": len(seen),
        "covered": len(seen) - len(uninsured_list),
        "uninsured": len(uninsured_list),
        "uninsured_list": uninsured_list,
    }
