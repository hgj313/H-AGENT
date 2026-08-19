"""每日打卡+保险覆盖检查服务

串联：同步打卡数据 → 检查保险覆盖 → 发送邮件提醒。

这是定时任务的回调入口，也是手动触发的入口。
"""

import logging
from datetime import datetime

from insurance_agent.tools import coverage_check
from insurance_agent.tools.insurance_reminder import load_config, save_config, send_reminder_email

logger = logging.getLogger(__name__)


def build_coverage_email_html(persons: list[dict], punch_date: str, scope_label: str = "") -> str:
    """构建保险覆盖检查的提醒邮件 HTML。

    Args:
        persons: 要展示的无保险人员列表（可按项目经理过滤，实现「每位经理只看自己项目」）
        punch_date: 打卡日期
        scope_label: 范围说明，如「您负责的项目」「全部项目（汇总）」
    """
    def render_person_rows(persons: list[dict]) -> str:
        rows = ""
        for i, p in enumerate(persons, 1):
            rows += f"""
            <tr>
                <td>{i}</td>
                <td>{p.get('name', '')}</td>
                <td>{p.get('id_number', '')}</td>
                <td>{p.get('project_name', '')}</td>
                <td>{p.get('team_name', '')}</td>
                <td>{p.get('supplier_name', '')}</td>
                <td>{p.get('category_name', '')}</td>
            </tr>"""
        return rows

    rows = render_person_rows(persons)

    header = """
    <tr>
        <th>#</th><th>姓名</th><th>身份证号</th><th>项目</th>
        <th>班组</th><th>劳务公司</th><th>劳务分类</th>
    </tr>"""

    uninsured_section = ""
    if persons:
        label_suffix = f" · {scope_label}" if scope_label else ""
        uninsured_section = f"""
        <h3 style="color:#e53e3e;margin:16px 0 8px;">🔴 无正常保单人员（{len(persons)}人{label_suffix}）</h3>
        <table style="width:100%;border-collapse:collapse;font-size:12px;">
            <thead>{header}</thead>
            <tbody>{rows}</tbody>
        </table>"""

    scope_prefix = f"{scope_label}，" if scope_label else ""
    return f"""
    <html><body style="font-family:'Microsoft YaHei',Arial,sans-serif;background:#f5f5f5;padding:20px">
    <div style="max-width:1100px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1)">
        <div style="background:linear-gradient(135deg,#e53e3e,#c53030);color:white;padding:20px 24px">
            <h2 style="margin:0">⚠️ 打卡人员保险提醒</h2>
            <p style="margin:4px 0 0;opacity:0.9">
                打卡日期 <b>{punch_date}</b>，
                {scope_prefix}共 <b>{len(persons)}</b> 人打卡无正常保单，请及时购买保险
            </p>
        </div>
        <div style="padding:16px 24px">
            {uninsured_section}
        </div>
        <div style="background:#fafafa;padding:12px 24px;color:#999;font-size:11px">
            本邮件由保险单识别系统自动发送 &mdash; {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
    </body></html>
    """


def run_daily_check(session_manager=None, punch_date: str = None, force: bool = False, projects_limit: int = None) -> dict:
    """执行每日打卡+保险覆盖检查（同步 → 对比 → 提醒）

    Args:
        session_manager: SessionManager 实例（用于同步打卡数据）
        punch_date: 打卡日期（默认今天）
        force: 强制重发，绕过"今日已发送过则跳过"的去重保护
        projects_limit: 测试用：只处理前 N 个项目的人员（None 或 0 = 不限制）。
                       短信和邮件都只涉及这 N 个项目，不会给每个项目都发一遍。

    Returns:
        完整执行结果
    """
    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")

    today = datetime.now().strftime("%Y-%m-%d")

    # 今日发送去重：避免同一天内多次手动/自动触发造成重复发送给经理
    # 调度器自身已按"日期"去重（scheduler._last_run_dates），这里再加一层
    # 防护覆盖手动重复点击、debug 多次调用等场景。force=True 可绕过。
    if not force and punch_date == today:
        try:
            cfg = load_config()
            last_send_date = (cfg.get("last_daily_check") or {}).get("punch_date")
            if last_send_date == today:
                result = {
                    "punch_date": punch_date,
                    "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "skipped": True,
                    "skip_reason": f"今日（{today}）已发送过保险覆盖检查提醒，跳过重复发送以避免打扰经理",
                    "last_check": cfg.get("last_daily_check"),
                }
                logger.info("run_daily_check: 今日已发送过，跳过（force=%s）", force)
                return result
        except Exception as e:
            logger.warning("读取 last_daily_check 去重状态失败: %s", e)

    result = {
        "punch_date": punch_date,
        "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sync": None,
        "coverage": None,
        "email": None,
        "sms": None,
    }

    # 1. 同步打卡数据（受「打卡同步功能」开关控制）
    sync_enabled = True
    try:
        from insurance_agent.infrastructure.scheduler import load_scheduler_config
        sync_enabled = load_scheduler_config().get("punch_sync_enabled", True)
    except Exception:
        pass

    if session_manager is not None and sync_enabled:
        sync_result = coverage_check.sync_punch_data(session_manager, punch_date)
        result["sync"] = sync_result
        if not sync_result.get("success"):
            result["success"] = False
            result["error"] = f"同步打卡数据失败: {sync_result.get('error')}"
            return result
    else:
        result["sync"] = {
            "success": True,
            "note": "打卡同步功能已关闭（或未提供 session_manager），跳过同步，仅检查现有数据",
        }

    # 2. 检查保险覆盖
    coverage = coverage_check.check_insurance_coverage(punch_date)
    result["coverage"] = coverage

    # 2.5 测试模式：限制只处理前 N 个项目的人员
    full_uninsured = coverage.get("uninsured_list", []) or []
    uninsured = full_uninsured
    if projects_limit and projects_limit > 0:
        # 按 project_name 去重取前 N 个项目
        seen_projects: list[str] = []
        limited: list[dict] = []
        for p in full_uninsured:
            proj = (p.get("project_name") or "").strip() or "未知项目"
            if proj not in seen_projects:
                if len(seen_projects) >= projects_limit:
                    continue
                seen_projects.append(proj)
            limited.append(p)
        result["projects_limit"] = projects_limit
        result["limited_projects"] = seen_projects
        uninsured = limited
        logger.info(
            "run_daily_check: 测试模式 projects_limit=%s，实际处理项目=%s（%s 人/%s 总项目）",
            projects_limit, seen_projects, len(uninsured), len({(p.get('project_name') or '').strip() for p in full_uninsured}),
        )

    # 3. 触发邮件提醒
    if uninsured:
        email_config = load_config().get("email", {})
        if email_config.get("enabled", True):
            email_result = _send_coverage_email(coverage, punch_date, email_config, uninsured)
            result["email"] = email_result
        else:
            result["email"] = {"success": False, "message": "邮件通知已禁用"}
    else:
        result["email"] = {"success": True, "message": "无异常人员，无需提醒"}

    # 4. 触发短信提醒
    if uninsured:
        result["sms"] = _send_coverage_sms(uninsured)
    else:
        result["sms"] = {"success": True, "message": "无异常人员，无需短信提醒"}

    result["success"] = True

    # 记录本次执行（用于"今日已发送过则跳过"的去重保护）
    try:
        cfg = load_config()
        cfg["last_daily_check"] = {
            "punch_date": punch_date,
            "check_time": result["check_time"],
            "total_punch": (result.get("coverage") or {}).get("total_punch"),
            "uninsured": (result.get("coverage") or {}).get("uninsured"),
            "email_success": (result.get("email") or {}).get("success"),
            "sms_success": (result.get("sms") or {}).get("success"),
            "force": bool(force),
            "projects_limit": projects_limit,
        }
        save_config(cfg)
    except Exception as e:
        logger.warning("保存 last_daily_check 失败: %s", e)

    return result


def _send_coverage_sms(uninsured: list[dict]) -> dict:
    """发送覆盖检查提醒短信（按项目 → 项目经理手机，每个项目一条）

    路由规则（按用户最新要求）：
    1) 每位项目经理手机：仅收到「自己项目上」打卡却无正常保险的人员，且汇总为
       **一条**短信（names = 该组第一人姓名，count = 总人数，模板渲染为
       「${project}项目上有黄希明等4人打卡上班未参保，请及时购买。详情请查看邮箱。」）。
    2) **不向固定手机号发送汇总短信**：汇总通知仅通过邮件（_send_coverage_email）
       路由至信息提醒配置的固定收件人邮箱。
    短信功能未启用或未配置凭证时跳过；无项目经理手机时跳过（汇总通过邮件兜底）。
    """
    from insurance_agent.tools.insurance_reminder import build_sms_messages
    from insurance_agent.tools.sms_sender import send_sms

    config = load_config()
    sms_config = config.get("sms", {})
    if not sms_config.get("enabled", False):
        return {"success": False, "message": "短信通知已禁用"}

    # 按项目分组无保险人员
    by_proj: dict[str, list[dict]] = {}
    for p in uninsured:
        proj = (p.get("project_name") or "").strip() or "未知项目"
        by_proj.setdefault(proj, []).append(p)

    # 构建 项目 -> 项目经理(姓名/手机/邮箱) 映射（取首个含经理信息的记录，
    # 即便部分打卡记录该项目经理字段为空，也能通过同项目其它记录补全）
    proj_manager: dict[str, dict] = {}
    for p in uninsured:
        proj = (p.get("project_name") or "").strip() or "未知项目"
        if proj not in proj_manager and (p.get("manager_phone") or p.get("manager_email")):
            proj_manager[proj] = {
                "name": p.get("project_manager", "") or "",
                "phone": p.get("manager_phone", "") or "",
                "email": p.get("manager_email", "") or "",
            }

    results = []

    # 仅按项目 → 项目经理本人手机发送聚合短信（每个项目一条）
    for proj, persons in by_proj.items():
        mgr = proj_manager.get(proj)
        if not mgr or not mgr["phone"]:
            continue  # 无经理手机的人员由邮件（汇总通道）兜底
        messages = build_sms_messages(persons, "project_name")
        if not messages:
            continue
        cfg = dict(sms_config)
        cfg["phone_numbers"] = [mgr["phone"]]
        r = send_sms(cfg, messages)
        r["target"] = f"{mgr['name'] or '未知经理'}({mgr['phone']})"
        r["type"] = "manager"
        results.append(r)

    sent = sum(1 for r in results if r.get("success"))
    if not results:
        return {"success": True, "message": "无需发送短信（无项目经理手机可发送）"}
    if sent == 0:
        return {"success": False, "message": "；".join(r.get("message", "") for r in results), "details": results}
    msg = f"已向 {len(results)} 个项目的项目经理发送聚合短信"
    return {"success": True, "message": msg, "details": results}


def _send_coverage_email(check_result, punch_date, email_config, uninsured) -> dict:
    """发送覆盖检查提醒邮件（双通道路由）

    路由规则（按用户要求）：
    1) 每位项目经理：仅收到「自己项目上」打卡却无正常保险的人员邮件（按 manager_email 分组）。
    2) 汇总：所有无正常保险人员汇总发送至「信息提醒配置」中的固定收件邮箱。
    两个通道独立发送，任一失败不影响另一通道。
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    sender = email_config.get("sender_email", "")
    password = email_config.get("sender_auth", "")
    fixed_recipients = email_config.get("recipient_emails", [])
    if isinstance(fixed_recipients, str):
        fixed_recipients = [r.strip() for r in fixed_recipients.split(",") if r.strip()]

    if not sender or not password:
        return {"success": False, "message": "邮箱配置不完整"}

    smtp_host = email_config.get("smtp_host", "smtp.qq.com")
    smtp_port = email_config.get("smtp_port", 465)

    # 通道1：按项目经理分组（每位经理只看自己项目）
    manager_map: dict = {}
    for p in uninsured:
        em = (p.get("manager_email") or "").strip()
        if em:
            manager_map.setdefault(em, []).append(p)

    results = []
    try:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        server.login(sender, password)

        # 通道1：项目经理（本人邮箱，仅自己项目人员）
        for em, persons in manager_map.items():
            subject = f"⚠️ 保险购买提醒 — {punch_date} 您负责项目 {len(persons)} 人未正常参保"
            try:
                msg = MIMEMultipart("alternative")
                msg["From"] = sender
                msg["To"] = em
                msg["Subject"] = subject
                msg.attach(MIMEText(build_coverage_email_html(persons, punch_date, "您负责的项目"), "html", "utf-8"))
                server.sendmail(sender, [em], msg.as_string())
                results.append({"target": em, "type": "manager", "success": True, "message": f"项目经理邮件({len(persons)}人)"})
            except Exception as e:
                results.append({"target": em, "type": "manager", "success": False, "message": f"失败:{e}"})

        # 通道2：汇总至固定收件人
        if fixed_recipients:
            subject = f"⚠️ 保险购买提醒（汇总）— {punch_date} 打卡 {len(uninsured)} 人无正常保单"
            try:
                msg = MIMEMultipart("alternative")
                msg["From"] = sender
                msg["To"] = ", ".join(fixed_recipients)
                msg["Subject"] = subject
                msg.attach(MIMEText(build_coverage_email_html(uninsured, punch_date, "全部项目汇总"), "html", "utf-8"))
                server.sendmail(sender, fixed_recipients, msg.as_string())
                results.append({"target": ",".join(fixed_recipients), "type": "aggregate", "success": True, "message": f"汇总邮件({len(uninsured)}人)"})
            except Exception as e:
                results.append({"target": ",".join(fixed_recipients), "type": "aggregate", "success": False, "message": f"失败:{e}"})

        server.quit()
    except Exception as e:
        return {"success": False, "message": f"邮件服务连接/登录失败: {e}"}

    sent = sum(1 for r in results if r.get("success"))
    if sent == 0:
        return {"success": False, "message": "；".join(r.get("message", "") for r in results) or "无邮件发送成功", "details": results}
    return {
        "success": True,
        "message": f"已发送 {sent} 封邮件（{len(manager_map)} 位项目经理 + 汇总至 {len(fixed_recipients)} 个固定收件人）",
        "details": results,
    }
