"""每日打卡+保险覆盖检查服务

串联：同步打卡数据 → 检查保险覆盖 → 发送邮件提醒。

这是定时任务的回调入口，也是手动触发的入口。
"""

import logging
from datetime import datetime

from insurance_agent.tools import coverage_check
from insurance_agent.tools.insurance_reminder import load_config, send_reminder_email

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


def run_daily_check(session_manager=None, punch_date: str = None) -> dict:
    """执行每日打卡+保险覆盖检查（同步 → 对比 → 提醒）

    Args:
        session_manager: SessionManager 实例（用于同步打卡数据）
        punch_date: 打卡日期（默认今天）

    Returns:
        完整执行结果
    """
    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")

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

    # 3. 触发邮件提醒
    uninsured = coverage.get("uninsured_list", [])

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
    return result


def _build_per_person_messages(persons: list[dict]) -> list[dict]:
    """回退用：将一组人员拆成「每人一条」短信变量（单姓名，兼容阿里云姓名类型）"""
    msgs = []
    proj = (persons[0].get("project_name") if persons else "") or "未知项目"
    total = str(len(persons))
    for p in persons:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        msgs.append({
            "project": (p.get("project_name") or "").strip() or proj,
            "names": name,
            "count": total,
        })
    return msgs


def _is_aliyun_var_spec_error(result: dict) -> bool:
    """判断是否为阿里云「变量规范」类拒绝（names 变量类型不匹配多人名）"""
    m = result.get("message", "")
    return ("变量规范" in m) or ("变量" in m and "规范" in m)


def _send_coverage_sms(uninsured: list[dict]) -> dict:
    """发送覆盖检查提醒短信（双通道路由，按项目聚合成一条）

    路由规则（按用户要求）：
    1) 每位项目经理手机：仅收到「自己项目上」打卡却无正常保险的人员，且汇总为
       **一条**短信（前若干姓名顿号分隔 + 总人数，如「黄希明、黄永琴、彭志忠等4人」）。
    2) 汇总：所有无正常保险人员按项目聚合后，逐项目发送汇总短信至「信息提醒
       配置」中的固定手机号。
    无项目经理手机的项目由固定收件人汇总兜底。
    短信功能未启用或未配置凭证时跳过。

    阿里云变量类型兼容：若短信服务商（阿里云）因 `names` 变量为「个人姓名」
    类型而拒绝多人名，会自动回退为「每人一条」以保证短信仍可送达，并在结果中
    标注 fallback，提示需将模板变量类型改为「文本/其他」。
    """
    from insurance_agent.tools.insurance_reminder import build_sms_messages
    from insurance_agent.tools.sms_sender import send_sms

    config = load_config()
    sms_config = config.get("sms", {})
    if not sms_config.get("enabled", False):
        return {"success": False, "message": "短信通知已禁用"}

    fixed_phones = sms_config.get("phone_numbers", []) or []
    if isinstance(fixed_phones, str):
        fixed_phones = [p.strip() for p in fixed_phones.split(",") if p.strip()]

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
    fallback_hint = False

    # 通道1：按项目 → 项目经理本人手机（每个项目一条聚合短信）
    for proj, persons in by_proj.items():
        mgr = proj_manager.get(proj)
        if not mgr or not mgr["phone"]:
            continue  # 无经理手机，交由固定收件人汇总兜底
        messages = build_sms_messages(persons, "project_name")
        if not messages:
            continue
        cfg = dict(sms_config)
        cfg["phone_numbers"] = [mgr["phone"]]
        r = send_sms(cfg, messages)
        # 阿里云变量类型拒绝多人名 → 自动回退每人一条
        if not r.get("success") and _is_aliyun_var_spec_error(r):
            r2 = send_sms(cfg, _build_per_person_messages(persons))
            r2["fallback"] = True
            r2["target"] = r.get("target")
            r2["type"] = r.get("type")
            r = r2
            fallback_hint = True
        r["target"] = f"{mgr['name'] or '未知经理'}({mgr['phone']})"
        r["type"] = "manager"
        results.append(r)

    # 通道2：汇总至固定手机号（每个项目一条聚合短信）
    if fixed_phones:
        for proj, persons in by_proj.items():
            messages = build_sms_messages(persons, "project_name")
            if not messages:
                continue
            cfg = dict(sms_config)
            cfg["phone_numbers"] = fixed_phones
            r = send_sms(cfg, messages)
            if not r.get("success") and _is_aliyun_var_spec_error(r):
                r2 = send_sms(cfg, _build_per_person_messages(persons))
                r2["fallback"] = True
                r2["target"] = r.get("target")
                r2["type"] = r.get("type")
                r = r2
                fallback_hint = True
            r["target"] = ",".join(fixed_phones)
            r["type"] = "aggregate"
            results.append(r)

    sent = sum(1 for r in results if r.get("success"))
    if not results:
        return {"success": True, "message": "无需发送短信（无项目经理手机且无固定收件人）"}
    if sent == 0:
        return {"success": False, "message": "；".join(r.get("message", "") for r in results), "details": results}
    msg = f"已向 {len([m for m in proj_manager.values() if m['phone']])} 位项目经理逐项目发送聚合短信，并向 {len(fixed_phones)} 个固定手机号逐项目发送汇总短信"
    if fallback_hint:
        msg += "（注：阿里云 names 变量仍为「个人姓名」类型，已自动回退每人一条；请将模板变量类型改为「文本/其他」以启用聚合短信）"
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
