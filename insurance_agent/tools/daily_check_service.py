"""每日打卡+保险覆盖检查服务

串联：同步打卡数据 → 检查保险覆盖 → 发送邮件提醒。

这是定时任务的回调入口，也是手动触发的入口。
"""

import logging
from datetime import datetime

from insurance_agent.tools import coverage_check
from insurance_agent.tools.insurance_reminder import load_config, send_reminder_email

logger = logging.getLogger(__name__)


def build_coverage_email_html(check_result: dict, punch_date: str) -> str:
    """构建保险覆盖检查的提醒邮件 HTML"""
    uninsured = check_result.get("uninsured_list", [])
    expired = check_result.get("expired_list", [])

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
                <td>{p.get('last_end_date', '') or '—'}</td>
            </tr>"""
        return rows

    uninsured_rows = render_person_rows(uninsured)
    expired_rows = render_person_rows(expired)

    header = """
    <tr>
        <th>#</th><th>姓名</th><th>身份证号</th><th>项目</th>
        <th>班组</th><th>劳务公司</th><th>劳务分类</th><th>上次保险到期</th>
    </tr>"""

    uninsured_section = ""
    if uninsured:
        uninsured_section = f"""
        <h3 style="color:#e53e3e;margin:16px 0 8px;">🔴 无保险人员（{len(uninsured)}人）</h3>
        <table style="width:100%;border-collapse:collapse;font-size:12px;">
            <thead>{header}</thead>
            <tbody>{uninsured_rows}</tbody>
        </table>"""

    expired_section = ""
    if expired:
        expired_section = f"""
        <h3 style="color:#dd6b20;margin:16px 0 8px;">🟠 保险已过期人员（{len(expired)}人）</h3>
        <table style="width:100%;border-collapse:collapse;font-size:12px;">
            <thead>{header}</thead>
            <tbody>{expired_rows}</tbody>
        </table>"""

    return f"""
    <html><body style="font-family:'Microsoft YaHei',Arial,sans-serif;background:#f5f5f5;padding:20px">
    <div style="max-width:1100px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1)">
        <div style="background:linear-gradient(135deg,#e53e3e,#c53030);color:white;padding:20px 24px">
            <h2 style="margin:0">⚠️ 打卡人员保险覆盖提醒</h2>
            <p style="margin:4px 0 0;opacity:0.9">
                打卡日期 <b>{punch_date}</b>，
                共 <b>{check_result.get('total_punch', 0)}</b> 人打卡，
                无保险 <b>{len(uninsured)}</b> 人，
                保险已过期 <b>{len(expired)}</b> 人
            </p>
        </div>
        <div style="padding:16px 24px">
            {uninsured_section}
            {expired_section}
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
    }

    # 1. 同步打卡数据
    if session_manager is not None:
        sync_result = coverage_check.sync_punch_data(session_manager, punch_date)
        result["sync"] = sync_result
        if not sync_result.get("success"):
            result["success"] = False
            result["error"] = f"同步打卡数据失败: {sync_result.get('error')}"
            return result
    else:
        result["sync"] = {"success": True, "note": "未提供 session_manager，跳过同步，仅检查现有数据"}

    # 2. 检查保险覆盖
    coverage = coverage_check.check_insurance_coverage(punch_date)
    result["coverage"] = coverage

    # 3. 触发邮件提醒
    uninsured = coverage.get("uninsured_list", [])
    expired = coverage.get("expired_list", [])

    if uninsured or expired:
        email_config = load_config().get("email", {})
        if email_config.get("enabled", True):
            # 构造提醒人员列表（合并无保险+已过期）
            alert_persons = []
            for p in uninsured:
                alert_persons.append({
                    "name": p.get("name", ""),
                    "id_number": p.get("id_number", ""),
                    "project_name": p.get("project_name", ""),
                    "team_name": p.get("team_name", ""),
                    "supplier_name": p.get("supplier_name", ""),
                    "category_name": p.get("category_name", ""),
                    "last_end_date": "",
                })
            for p in expired:
                alert_persons.append({
                    "name": p.get("name", ""),
                    "id_number": p.get("id_number", ""),
                    "project_name": p.get("project_name", ""),
                    "team_name": p.get("team_name", ""),
                    "supplier_name": p.get("supplier_name", ""),
                    "category_name": p.get("category_name", ""),
                    "last_end_date": p.get("last_end_date", ""),
                })

            # 复用 reminder 的邮件发送，但用覆盖检查的 HTML
            email_result = _send_coverage_email(
                coverage, punch_date, email_config, uninsured, expired
            )
            result["email"] = email_result
        else:
            result["email"] = {"success": False, "message": "邮件通知已禁用"}
    else:
        result["email"] = {"success": True, "message": "无异常人员，无需提醒"}

    result["success"] = True
    return result


def _send_coverage_email(check_result, punch_date, email_config, uninsured, expired) -> dict:
    """发送覆盖检查提醒邮件"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    sender = email_config.get("sender_email", "")
    password = email_config.get("sender_auth", "")
    recipients = email_config.get("recipient_emails", [])
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]

    if not sender or not password or not recipients:
        return {"success": False, "message": "邮箱配置不完整"}

    smtp_host = email_config.get("smtp_host", "smtp.qq.com")
    smtp_port = email_config.get("smtp_port", 465)

    total_alert = len(uninsured) + len(expired)
    subject = f"⚠️ 保险覆盖提醒 — {punch_date} 打卡 {total_alert} 人需购买/续保"

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(build_coverage_email_html(check_result, punch_date), "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        return {"success": True, "message": f"已发送提醒邮件到 {', '.join(recipients)}，{total_alert} 人需处理"}
    except Exception as e:
        return {"success": False, "message": f"邮件发送失败: {e}"}
