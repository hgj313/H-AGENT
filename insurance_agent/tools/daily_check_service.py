"""每日打卡+保险覆盖检查服务

串联：同步打卡数据 → 检查保险覆盖 → 发送邮件提醒。

这是定时任务的回调入口，也是手动触发的入口。
"""

import logging
from datetime import datetime

from insurance_agent.tools import coverage_check
from insurance_agent.tools.insurance_reminder import load_config, save_config, send_reminder_email
from insurance_agent.tools.notification_audit import log_send

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
            本邮件由保险管理AI助手自动发送 &mdash; {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
    </body></html>
    """


def run_daily_check(session_manager=None, punch_date: str = None, force: bool = False) -> dict:
    """执行每日打卡+保险覆盖检查（同步 → 对比 → 提醒）

    Args:
        session_manager: SessionManager 实例（用于同步打卡数据）
        punch_date: 打卡日期（默认今天）
        force: 强制重发，绕过"今日已发送过则跳过"的去重保护

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
        try:
            sync_result = coverage_check.sync_punch_data(session_manager, punch_date)
        except Exception as e:  # noqa: BLE001
            # 沙箱环境 watchdog 启动的进程可能因 token 受限无法写入 db，
            # 此时不阻断后续 SMS/邮件发送流程，直接用 punch_records ���有数据。
            logger.warning("同步打卡数据异常（已忽略，继续后续步骤）: %s", e)
            sync_result = {"success": False, "error": str(e), "skipped": True}
        result["sync"] = sync_result
        if not sync_result.get("success") and not sync_result.get("skipped"):
            result["success"] = False
            result["error"] = f"同步打卡数据失败: {sync_result.get('error')}"
            return result
    else:
        result["sync"] = {
            "success": True,
            "note": "打卡同步功能已关闭（或未提供 session_manager），跳过同步，仅检查现有数据",
        }

    # 2. 检查保险覆盖
    #    测试模式：punch_table 为 "punch_records_test" 时，从副本表读取经理联系方式
    #    生产模式：默认 "punch_records"
    punch_table = "punch_records"
    try:
        cfg_for_table = load_config()
        cfg_table = (cfg_for_table.get("punch_table_for_sms") or "").strip()
        if cfg_table and cfg_table != "punch_records":
            # 白名单：仅允许 punch_records / punch_records_test / punch_records_backup_*
            if cfg_table == "punch_records_test" or cfg_table.startswith("punch_records_backup_"):
                punch_table = cfg_table
                logger.warning(
                    "⚠️ daily_check 当前使用测试表 %r（生产表 %r 暂未读取），"
                    "测试完毕后请改回 punch_records",
                    punch_table, "punch_records",
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 punch_table_for_sms 失败，使用默认值: %s", e)

    coverage = coverage_check.check_insurance_coverage(punch_date, punch_table=punch_table)
    result["coverage"] = coverage
    result["punch_table"] = punch_table

    uninsured = coverage.get("uninsured_list", []) or []

    # 3. 触发邮件提醒（每经理一封 + 汇总到固定收件人）
    if uninsured:
        email_config = load_config().get("email", {})
        if email_config.get("enabled", True):
            email_result = _send_coverage_email(coverage, punch_date, email_config, uninsured, send_aggregate=True)
            result["email"] = email_result
        else:
            result["email"] = {"success": False, "message": "邮件通知已禁用"}
    else:
        result["email"] = {"success": True, "message": "无异常人员，无需提醒"}

    # 4. 触发短信提醒
    if uninsured:
        if force:
            logger.warning(
                "run_daily_check: force=true 跳过「今日已发送」全流程保护，但仍受 "
                "_send_coverage_sms 内部 per-phone dedup 约束（同一手机号一天内仅一条）"
            )
        result["sms"] = _send_coverage_sms(uninsured, punch_date=punch_date)
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
        }
        save_config(cfg)
    except Exception as e:
        logger.warning("保存 last_daily_check 失败: %s", e)

    return result


def _send_coverage_sms(uninsured: list[dict], punch_date: str = None) -> dict:
    """发送覆盖检查提醒短信（按项目 → 项目经理手机，每个项目一条）

    路由规则（按用户最新要求）：
    1) 每位项目经理手机：仅收到「自己项目上」打卡却无正常保险的人员，且汇总为
       **一条**短信（names = 该组第一人姓名，count = 总人数，模板渲染为
       「${project}项目上有黄希明等4人打卡上班未参保，请及时购买。详情请查看邮箱。」）。
    2) **不向固定手机号发送汇总短信**：汇总通知仅通过邮件（_send_coverage_email）
       路由至信息提醒配置的固定收件人邮箱。

    **重复发送保护（强制）**：
    - per-phone dedup：每个手机号在同一个 punch_date 下最多收到一条 SMS。
    - 即使 force=True 也不绕过此保护（force 只绕过"今日已发送"的全流程跳过）。
    - 状态写入 .reminder_config.json 的 daily_sms_sent_today 字段。
    - 仅在切换 punch_date（跨天）或换手机号（不同经理）时才会再次发送。
    - 这是防止生产+测试双重触发的最后一道防线，杜绝「7条重复」类事故。

    短信功能未启用或未配置凭证时跳过；无项目经理手机时跳过（汇总通过邮件兜底）。
    """
    from insurance_agent.tools.insurance_reminder import build_sms_messages
    from insurance_agent.tools.sms_sender import send_sms

    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")

    config = load_config()
    sms_config = config.get("sms", {})
    if not sms_config.get("enabled", False):
        return {"success": False, "message": "短信通知已禁用"}

    # 加载今日已发送过 SMS 的手机号集合（per-phone dedup）
    sent_state = config.get("daily_sms_sent_today") or {}
    already_sent: set[str] = (
        set(sent_state.get("phones", []))
        if sent_state.get("punch_date") == punch_date
        else set()
    )

    # 一次性构建所有项目的短信模板变量（build_sms_messages 内部已按项目分组，每项目 1 条）
    messages_by_project: dict[str, dict] = {
        m["project"]: m for m in build_sms_messages(uninsured, "project_name")
    }
    if not messages_by_project:
        return {"success": True, "message": "无需发送短信（无可构建的模板变量）"}

    # 构建 项目 -> 项目经理 映射（首个含手机号的记录即可补全该项目的经理信息）
    proj_manager: dict[str, dict] = {}
    for p in uninsured:
        proj = (p.get("project_name") or "").strip() or "未知项目"
        if proj not in proj_manager and p.get("manager_phone"):
            proj_manager[proj] = {
                "name": p.get("project_manager", "") or "",
                "phone": p.get("manager_phone", "") or "",
                "email": p.get("manager_email", "") or "",
            }

    results: list[dict] = []
    newly_sent: list[str] = []

    for proj, msg_vars in messages_by_project.items():
        mgr = proj_manager.get(proj)
        if not mgr or not mgr["phone"]:
            # 无经理手机的人员由邮件（汇总通道）兜底
            log_send(
                channel="daily_check", kind="sms", to=[],
                project=proj, manager=mgr["name"] if mgr else "",
                person_count=msg_vars.get("count", 0),
                person_names=[msg_vars.get("names", "")],
                success=False, result="无经理手机号，跳过短信发送（由邮件兜底）",
            )
            continue
        phone = mgr["phone"]
        # per-phone dedup：同一天同一手机号已发送过则跳过（不论 force）
        if phone in already_sent:
            results.append({
                "target": f"{mgr['name'] or '未知经理'}({phone})",
                "type": "manager",
                "skipped": True,
                "message": f"{punch_date} 该手机号已发送过提醒，跳过（per-phone dedup）",
            })
            log_send(
                channel="daily_check", kind="sms", to=[phone],
                project=proj, manager=mgr["name"], person_count=msg_vars.get("count", 0),
                person_names=[msg_vars.get("names", "")],
                success=False, result=f"{punch_date} 该手机号已发送过提醒，跳过（per-phone dedup）",
            )
            continue
        cfg = dict(sms_config)
        cfg["phone_numbers"] = [phone]
        r = send_sms(cfg, [msg_vars])
        r["target"] = f"{mgr['name'] or '未知经理'}({phone})"
        r["type"] = "manager"
        results.append(r)
        # 审计：实际发送结果
        log_send(
            channel="daily_check", kind="sms", to=[phone],
            project=proj, manager=mgr["name"],
            person_count=msg_vars.get("count", 0),
            person_names=[msg_vars.get("names", "")],
            success=bool(r.get("success")),
            result=r.get("message", ""),
            error="" if r.get("success") else r.get("message", ""),
        )
        if r.get("success"):
            newly_sent.append(phone)

    # 持久化本次发送的手机号集合，用于下次 per-phone dedup
    if newly_sent:
        merged = list(already_sent | set(newly_sent))
        config["daily_sms_sent_today"] = {
            "punch_date": punch_date,
            "phones": merged,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            save_config(config)
        except Exception as e:
            logger.warning("保存 daily_sms_sent_today 失败（不影响本次发送）: %s", e)

    sent = sum(1 for r in results if r.get("success"))
    skipped = sum(1 for r in results if r.get("skipped"))
    if not results:
        return {"success": True, "message": "无需发送短信（无项目经理手机可发送）"}
    if sent == 0 and skipped == 0:
        return {"success": False, "message": "；".join(r.get("message", "") for r in results), "details": results}
    msg = f"短信：成功 {sent} 条" + (f"，跳过 {skipped} 条（已发过）" if skipped else "")
    return {"success": True, "message": msg, "details": results}


def _send_coverage_email(check_result, punch_date, email_config, uninsured, send_aggregate: bool = True) -> dict:
    """发送覆盖检查提醒邮件（双通道路由）

    路由规则（按用户要求）：
    1) 每位项目经理：仅收到「自己项目上」打卡却无正常保险的人员邮件（按 manager_email 分组）。
    2) 汇总：所有无正常保险人员汇总发送至「信息提醒配置」中的固定收件邮箱。
    两个通道独立发送，任一失败不影响另一通道。

    Args:
        send_aggregate: 是否发送汇总邮件。
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

    # 通道1：按 (项目经理, 项目) 分组（每位经理只看自己项目上的人员）
    # 不用 manager_email 作为分组键：测试模式下所有经理共享同一测试邮箱时，
    # 会被合并成一封邮件。改用 (manager_name, project_name) 保证每经理每项目一封邮件。
    manager_map: dict = {}
    manager_email_by_key: dict = {}
    for p in uninsured:
        mgr_name = (p.get("project_manager") or "").strip()
        proj_name = (p.get("project_name") or "").strip()
        em = (p.get("manager_email") or "").strip()
        if not em:
            continue
        # 分组键：经理+项目；空经理也按项目分组
        key = (mgr_name or "(未知经理)", proj_name or "(未知项目)")
        manager_map.setdefault(key, []).append(p)
        # 同 key 的所有记录应当使用同一邮箱（取第一个非空值即可）
        manager_email_by_key.setdefault(key, em)

    results = []
    try:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        server.login(sender, password)

        # 通道1：项目经理（本人邮箱，仅自己项目人员）
        for key, persons in manager_map.items():
            em = manager_email_by_key[key]
            mgr_label = key[0]
            subject = f"⚠️ 保险购买提醒 — {punch_date} 您负责项目 {len(persons)} 人未正常参保"
            try:
                msg = MIMEMultipart("alternative")
                msg["From"] = sender
                msg["To"] = em
                msg["Subject"] = subject
                msg.attach(MIMEText(build_coverage_email_html(persons, punch_date, "您负责的项目"), "html", "utf-8"))
                server.sendmail(sender, [em], msg.as_string())
                results.append({"target": em, "type": "manager", "success": True, "message": f"项目经理邮件({len(persons)}人)→{mgr_label}", "manager": mgr_label, "project": key[1]})
                # 审计：项目经理邮件成功
                log_send(
                    channel="daily_check", kind="email", to=[em],
                    project=key[1], manager=mgr_label,
                    person_count=len(persons),
                    person_names=[p.get("name", "") for p in persons],
                    subject=subject, success=True,
                    result=f"项目经理邮件({len(persons)}人)",
                )
            except Exception as e:
                results.append({"target": em, "type": "manager", "success": False, "message": f"失败:{e}"})
                # 审计：失败
                log_send(
                    channel="daily_check", kind="email", to=[em],
                    project=key[1], manager=mgr_label,
                    person_count=len(persons),
                    person_names=[p.get("name", "") for p in persons],
                    subject=subject, success=False,
                    result="SMTP 异常", error=str(e),
                )

        # 通道1.5：同经理多项目汇总（如刘会洪同时负责 2 个项目，发送 2 封内容不同的邮件）
        # 由 manager_map 的 key 已包含 project_name 自动覆盖，无需额外处理

        # 通道2：汇总至固定收件人（测试模式下跳过，避免打扰固定收件人）
        if send_aggregate and fixed_recipients:
            subject = f"⚠️ 保险购买提醒（汇总）— {punch_date} 打卡 {len(uninsured)} 人无正常保单"
            try:
                msg = MIMEMultipart("alternative")
                msg["From"] = sender
                msg["To"] = ", ".join(fixed_recipients)
                msg["Subject"] = subject
                msg.attach(MIMEText(build_coverage_email_html(uninsured, punch_date, "全部项目汇总"), "html", "utf-8"))
                server.sendmail(sender, fixed_recipients, msg.as_string())
                results.append({"target": ",".join(fixed_recipients), "type": "aggregate", "success": True, "message": f"汇总邮件({len(uninsured)}人)"})
                # 审计：汇总邮件成功
                log_send(
                    channel="daily_check", kind="email", to=list(fixed_recipients),
                    project="（汇总）", manager="",
                    person_count=len(uninsured),
                    person_names=[p.get("name", "") for p in uninsured],
                    subject=subject, success=True,
                    result=f"汇总邮件至 {len(fixed_recipients)} 个固定收件人",
                )
            except Exception as e:
                results.append({"target": ",".join(fixed_recipients), "type": "aggregate", "success": False, "message": f"失败:{e}"})
                # 审计：失败
                log_send(
                    channel="daily_check", kind="email", to=list(fixed_recipients),
                    project="（汇总）", manager="",
                    person_count=len(uninsured),
                    person_names=[p.get("name", "") for p in uninsured],
                    subject=subject, success=False,
                    result="SMTP 异常", error=str(e),
                )

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
