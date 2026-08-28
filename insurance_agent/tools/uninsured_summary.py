"""未参保人员定时汇总（保险管理人员通知）

背景：
- 之前实时消费每发现一条未参保人员都会立即发邮件给保险管理人员，
  导致邮件刷屏、不便查看。
- 本模块把「保险管理人员汇总邮件」从实时链路剥离，改为定时汇总：
    - 每天上午 09:00  汇总一次
    - 每天下午 16:30 汇总一次（含上午已发过的人员，方便保险管理人员
      在下班前再做一次完整复核）

数据源：
- punch_records（今日所有打卡）
- insurance_personnel（保单人员，状态='正常'）

触发方式：
- 由 web_app/server.py 注册到全局 Scheduler：
    add_task("morning_summary", ..., "summary_morning_time")
    add_task("afternoon_summary", ..., "summary_afternoon_time")
- 测试模式（notification_test_mode=true）：汇总邮件统一发到 test_email
- 生产模式（notification_test_mode=false）：汇总邮件统一发到 insurance_manager_emails
  （未配置时退回 email.recipient_emails）
"""

import json
import os
import smtplib
from collections import defaultdict
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from insurance_agent.infrastructure import database as db
from insurance_agent.tools.insurance_reminder import load_config
from insurance_agent.tools.daily_check_service import build_coverage_email_html
from insurance_agent.tools.feishu_webhook_pusher import push_uninsured_summary
from insurance_agent.tools.notification_audit import log_send

SUMMARY_LOG = r"C:\insurance-automation\uninsured_summary.log"


def _log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(SUMMARY_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# ============ 数据查询 ============

def get_today_uninsured_persons(today_str: str = None) -> list:
    """查询今日所有打过卡但无「正常」保单的人员（按身份证号去重）。

    SQL 逻辑（LEFT JOIN + IS NULL）：
        找出 punch_records 当日所有记录，
        LEFT JOIN insurance_personnel（同身份证号 + 状态='正常'），
        WHERE ip.id_number IS NULL → 即打过卡但无任何正常保单。

    Args:
        today_str: 打卡日期 YYYY-MM-DD，默认今天

    Returns:
        list of dicts（与 build_coverage_email_html 的 persons 参数兼容）：
            [{name, id_number, project_name, team_name, supplier_name,
              category_name, project_manager, manager_phone, manager_email,
              punch_time}, ...]
    """
    if not today_str:
        today_str = datetime.now().strftime("%Y-%m-%d")

    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        # 用 GROUP BY 去重（同一人同一项目多次打卡只算一次）
        cursor.execute(
            """
            SELECT pr.member_name,
                   pr.identification_number,
                   pr.project_name,
                   pr.team_name,
                   pr.supplier_name,
                   pr.category_name,
                   pr.project_manager,
                   pr.manager_phone,
                   pr.manager_email,
                   MIN(pr.punch_time) AS first_punch_time
            FROM punch_records pr
            LEFT JOIN insurance_personnel ip
                ON pr.identification_number = ip.id_number
               AND ip.status = '正常'
            WHERE pr.punch_date = ?
              AND pr.identification_number IS NOT NULL
              AND pr.identification_number != ''
              AND pr.identification_number != 'undefined'
              AND ip.id_number IS NULL
            GROUP BY pr.identification_number, pr.project_name
            ORDER BY pr.project_name, pr.member_name
            """,
            (today_str,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    result = []
    for r in rows:
        result.append({
            "name": r[0] or "",
            "id_number": r[1] or "",
            "project_name": r[2] or "",
            "team_name": r[3] or "",
            "supplier_name": r[4] or "",
            "category_name": r[5] or "",
            "project_manager": r[6] or "",
            "manager_phone": r[7] or "",
            "manager_email": r[8] or "",
            "punch_time": r[9] or "",
        })
    return result


# ============ 邮件发送 ============

def _send_smtp(recipients: list, subject: str, html: str, email_config: dict, *, channel: str = "summary", person_count: int = 0, person_names=None) -> bool:
    """通用 SMTP 发送（与 realtime_punch_consumer._send_email_smtp 一致）。

    写审计日志：成功 / 失败 / 配置缺失都会记录到 notification_audit.jsonl。
    """
    recipients = [r.strip() for r in (recipients or []) if str(r).strip()]
    if not recipients:
        _log("邮件发送跳过：无收件人")
        log_send(
            channel=channel, kind="email", to=[],
            person_count=person_count, person_names=person_names,
            subject=subject, success=False, result="无收件人",
        )
        return False
    sender = email_config.get("sender_email", "")
    password = email_config.get("sender_auth", "")
    if not sender or not password:
        _log("邮件发送跳过：发件人配置不完整")
        log_send(
            channel=channel, kind="email", to=recipients,
            person_count=person_count, person_names=person_names,
            subject=subject, success=False, result="发件人配置不完整",
        )
        return False
    smtp_host = email_config.get("smtp_host", "smtp.qq.com")
    smtp_port = email_config.get("smtp_port", 465)
    try:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        server.login(sender, password)
        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        _log(f"邮件发送成功 -> {recipients} | {subject}")
        # 审计
        log_send(
            channel=channel, kind="email", to=recipients,
            person_count=person_count, person_names=person_names,
            subject=subject, success=True,
            result=f"已发送至 {len(recipients)} 个收件人",
        )
        return True
    except Exception as e:
        _log(f"邮件发送失败 -> {recipients}: {e}")
        log_send(
            channel=channel, kind="email", to=recipients,
            person_count=person_count, person_names=person_names,
            subject=subject, success=False, result="SMTP 异常",
            error=str(e),
        )
        return False


def _resolve_recipients(cfg: dict) -> list:
    """解析汇总邮件收件人（保险管理人员）。

    汇总邮件（每日 9:00 / 16:30）始终按用户配置的收件人列表发送，
    与 notification_test_mode 解耦：
    - 实时通知（每发现一个未参保人员）受 test_mode 控制 → 开发期只发到 test_email
    - 定时汇总（保险管理人员看全局）应该发到所有配置的真实收件人

    优先级：
    1. insurance_manager_emails（保险管理人员专用列表）
    2. 兜底：email.recipient_emails（信息提醒配置的固定收件人）
    """
    # 优先：保险管理人员专用收件人
    mgrs = [e.strip() for e in (cfg.get("insurance_manager_emails") or []) if str(e).strip()]
    if not mgrs:
        # 兜底：信息提醒配置中的所有收件人
        mgrs = [e.strip() for e in (cfg.get("email", {}).get("recipient_emails") or []) if str(e).strip()]
    return mgrs


# ============ 汇总入口（调度器回调） ============

def run_uninsured_summary(session_manager=None, period: str = "morning",
                          punch_date: str = None, force: bool = False) -> dict:
    """未参保人员汇总入口（被调度器调用）。

    Args:
        session_manager: SessionManager 实例（保留参数，未来可用于拉取 ERP 项目主数据补全经理联系方式）
        period: "morning" 或 "afternoon"（仅用于邮件标题区分）
        punch_date: 打卡日期 YYYY-MM-DD（默认今天）
        force: 强制重发（绕过 scheduler 同日去重保护，方便测试）

    Returns:
        dict: {period, punch_date, uninsured_count, recipients, success, error}
    """
    if punch_date is None:
        punch_date = datetime.now().strftime("%Y-%m-%d")

    period_label = "上午" if period == "morning" else "下午"
    _log(f"=== {period_label}汇总开始 ({punch_date}) ===")

    # 1) 查询今日所有未参保人员
    try:
        persons = get_today_uninsured_persons(punch_date)
    except Exception as e:
        _log(f"查询未参保人员失败: {e}")
        return {
            "period": period,
            "punch_date": punch_date,
            "uninsured_count": 0,
            "recipients": [],
            "success": False,
            "error": str(e),
        }

    _log(f"查询到 {len(persons)} 名未参保人员")

    # 2) 加载配置 + 收件人
    cfg = load_config()
    recipients = _resolve_recipients(cfg)
    if not recipients:
        _log(f"无收件人（{'测试' if cfg.get('notification_test_mode') else '生产'}模式均未配置）")
        return {
            "period": period,
            "punch_date": punch_date,
            "uninsured_count": len(persons),
            "recipients": [],
            "success": False,
            "error": "no recipients",
        }

    # 3) 即使无人未参保，也按"零数据"邮件发送（让收件人知道今天已检查过）
    email_config = cfg.get("email", {}) or {}
    if not email_config.get("enabled", True):
        _log("邮件未启用，跳过汇总发送")
        return {
            "period": period,
            "punch_date": punch_date,
            "uninsured_count": len(persons),
            "recipients": recipients,
            "success": False,
            "error": "email disabled",
        }

    # 4) 生成 HTML 邮件
    subject = (
        f"⚠️ 未参保人员汇总（{period_label}） — {punch_date} "
        f"共 {len(persons)} 人未正常参保"
    )
    scope_label = f"{period_label}汇总（含上午已通知人员）" if period == "afternoon" else f"{period_label}汇总"
    html = build_coverage_email_html(persons, punch_date, scope_label)

    # 5) 发送
    ok = _send_smtp(
        recipients, subject, html, email_config,
        channel=f"summary_{period}",
        person_count=len(persons),
        person_names=[p.get("name", "") for p in persons],
    )

    # 5.5) 飞书多维表格同步：异步批量推送（即使邮件发送失败也会尝试推飞书，确保数据同步）
    try:
        if persons:
            source_tag = f"summary_{period}"  # summary_morning / summary_afternoon
            feishu_pushed = push_uninsured_summary(persons, source=source_tag, punch_date=punch_date)
            _log(f"飞书多维表格异步推送 {feishu_pushed} 条（{source_tag}）")
    except Exception as e:
        _log(f"飞书 webhook 入队异常（不影响主流程）: {e}")

    # 6) 记录已发送（防止同日重复发）
    _mark_summary_sent(period, punch_date)

    return {
        "period": period,
        "punch_date": punch_date,
        "uninsured_count": len(persons),
        "recipients": recipients,
        "success": ok,
    }


# ============ 同日去重持久化 ============

SUMMARY_STATE_PATH = r"C:\insurance-automation\uninsured_summary_state.json"


def _load_summary_state() -> dict:
    if os.path.exists(SUMMARY_STATE_PATH):
        try:
            with open(SUMMARY_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_summary_state(state: dict) -> None:
    try:
        with open(SUMMARY_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log(f"保存汇总状态失败: {e}")


def _mark_summary_sent(period: str, punch_date: str) -> None:
    """记录某时段已发送（防止同日重复；服务重启也会被 scheduler 同日去重再保一道）。"""
    state = _load_summary_state()
    state.setdefault(punch_date, {})[period] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_summary_state(state)