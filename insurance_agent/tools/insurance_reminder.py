"""保险到期提醒 — QQ邮箱自动发送

功能：
- 读取人员清单数据（Excel模板 + extraction_results.json）
- 筛选到期日临近的被保人员
- 通过QQ邮箱SMTP发送HTML表格提醒邮件
- 邮件包含清单的全部字段

使用方式：
    python insurance_agent/tools/insurance_reminder.py
    # 或作为定时任务每天执行

配置通过 JSON 文件管理，路径: C:/insurance-automation/.reminder_config.json
也可通过 API 端点 GET/PUT /api/v1/reminder/config 在线管理
"""

import json
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import openpyxl

# ============ 提醒文案默认模板（均可在前端「信息提醒配置」覆盖，后台不写死）============
# 变量占位符：${project}/${names}/${count}（短信）、${target_date}/${total}/${days_text}（邮件）
SMS_TEMPLATE = "${project}项目上有${names}等${count}人打卡上班却无保险，请及时购买。详情请查看邮箱。"
SMS_TEMPLATE_VARS = {
    "project": "项目名称",
    "names": "无保险人员姓名（最多3人，顿号分隔）",
    "count": "该项目无保险总人数",
}
SMS_MAX_NAMES = 3

EMAIL_SUBJECT_DEFAULT = "⚠️ 保险到期提醒 — ${target_date} 到期 ${total} 人"
EMAIL_TITLE_DEFAULT = "⚠️ 保险到期提醒"
EMAIL_SUBTITLE_DEFAULT = "以下人员保险将于 ${target_date} 到期，请及时处理续保"
EMAIL_FOOTER_DEFAULT = "本邮件由保险管理AI助手自动发送"

EXPIRY_SUBJECT_DEFAULT = "⏰ 保险即将到期提醒 — ${days_text}到期 ${total} 人，请及时续保"
EXPIRY_TITLE_DEFAULT = "⏰ 保险即将到期提醒"
EXPIRY_SUBTITLE_DEFAULT = "以下人员保险将在 ${days_text} 到期（最晚 ${target_date}），请及时续保"


def render_template(tpl: str, **vars) -> str:
    """将 ${变量名} 占位符替换为实际值；未提供的变量保持原样。"""
    if not tpl:
        return ""
    for k, v in vars.items():
        tpl = tpl.replace("${%s}" % k, str(v))
    return tpl


# ============ 默认配置 (首次使用时写入配置文件) ============
DEFAULT_CONFIG = {
    "email": {
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "sender_email": "1337382541@qq.com",
        "sender_auth": "qwutucsktjwobaha",
        "recipient_emails": ["1130530657@qq.com"],
        "enabled": True,
        # ===== 以下文案均可在前端「信息提醒配置」中灵活修改（后台仅作默认值）=====
        "subject_template": EMAIL_SUBJECT_DEFAULT,
        "title": EMAIL_TITLE_DEFAULT,
        "subtitle_template": EMAIL_SUBTITLE_DEFAULT,
        "footer": EMAIL_FOOTER_DEFAULT,
        "expiry_title": EXPIRY_TITLE_DEFAULT,
        "expiry_subtitle_template": EXPIRY_SUBTITLE_DEFAULT,
    },
    "sms": {
        "enabled": False,               # 短信通知启用开关
        "provider": "aliyun",           # aliyun / tencent
        "access_key_id": "",            # 阿里云 AccessKey ID / 腾讯云 SecretId
        "access_key_secret": "",        # 阿里云 AccessKey Secret / 腾讯云 SecretKey
        "sdk_app_id": "",               # 腾讯云专用 SDKAppID
        "sign_name": "",                # 短信签名（需服务商审核）
        "template_code": "",            # 短信模板 Code / TemplateId（需服务商审核）
        "region": "",                   # 区域（可选，缺省 aliyun=cn-hangzhou / tencent=ap-guangzhou）
        "phone_numbers": [],            # 接收手机号列表
        "template_content": SMS_TEMPLATE,  # 短信正文模板，可在前端编辑（申请模板时提交的原文）
    },
    "check_days": [1, 3, 7],  # 提前1/3/7天检查
    "data_source": "json",
}

# 数据源路径（统一路径配置，支持 Docker 部署环境变量覆盖）
from insurance_agent.infrastructure.paths import PROJECT_ROOT, REMINDER_CONFIG_PATH
from insurance_agent.tools.notification_audit import log_send
CONFIG_PATH = REMINDER_CONFIG_PATH
EXCEL_PATH = os.path.join(PROJECT_ROOT, "最新保险数据下载模板.xlsx")
JSON_PATH = os.path.join(PROJECT_ROOT, "extraction_results.json")

# CSV输出的全部字段（按此顺序展示）
ALL_FIELDS = [
    ("姓名", "name"),
    ("证件号码", "id_number"),
    ("证件类型", "id_type"),
    ("出生日期", "birth_date"),
    ("所属公司", "company"),
    ("批改类型", "modification_type"),
    ("起始时间", "start_date"),
    ("起止时间", "end_date"),
    ("岗位名称", "job_title"),
    ("保险公司", "insurance_company"),
    ("保单号", "policy_number"),
    ("来源文件", "file_name"),
]


# ============ 短信提醒模板 ============

# SMS_TEMPLATE / SMS_TEMPLATE_VARS / SMS_MAX_NAMES 已统一定义于文件顶部
# （后台默认模板，可在前端「信息提醒配置」中编辑覆盖）。




# ============ 邮件文案默认模板（均可在前端「信息提醒配置」覆盖，后台不写死）============
# EMAIL_SUBJECT_DEFAULT / EMAIL_TITLE_DEFAULT / EMAIL_SUBTITLE_DEFAULT / EMAIL_FOOTER_DEFAULT
# 及 EXPIRY_* 默认模板、render_template 已统一定义于文件顶部（可在前端编辑覆盖）。




def build_sms_messages(uninsured_list: list[dict], key_field: str = "project_name", max_names: int = SMS_MAX_NAMES) -> list[dict]:
    """从无保险人员列表构建短信模板变量（按 key_field 聚合，每分组仅一条）

    按 key_field（默认 project_name）分组，每个分组（即每个项目）只生成
    **一条**聚合短信：names = 该组**第一人**的姓名（单姓名，符合阿里云
    「个人姓名」变量规范），count = 该组总人数。模板渲染后为
    「${project}项目上有${names}等${count}人打卡上班却无保险...」，即
    「华南保利...项目上有黄希明等4人打卡上班却无保险...」。

    这样每个项目只发一条短信，且 names 为单一真实姓名，阿里云「个人姓名」
    变量类型可直接接受，无需修改短信模板。max_names 仅作兼容保留（不再用于
    截断多人名）。
    """
    if not uninsured_list:
        return []

    by_key: dict[str, list[dict]] = {}
    for p in uninsured_list:
        key = (p.get(key_field) or "").strip() or "未知项目"
        by_key.setdefault(key, []).append(p)

    messages = []
    for key, persons in by_key.items():
        total = len(persons)
        # 仅取第一人姓名（单姓名，符合阿里云「个人姓名」变量规范）
        first_name = ""
        for p in persons:
            n = (p.get("name") or "").strip()
            if n:
                first_name = n
                break
        if not first_name:
            continue
        messages.append({
            "project": key,
            "names": first_name,
            "count": str(total),
        })
    return messages


def load_config(config_path: str = CONFIG_PATH) -> dict:
    """加载提醒配置，不存在时返回默认值。"""
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 合并默认值，确保所有字段存在
            merged = dict(DEFAULT_CONFIG)
            _deep_update(merged, cfg)
            return merged
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict, config_path: str = CONFIG_PATH) -> bool:
    """保存提醒配置。"""
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


def _deep_update(base: dict, update: dict) -> None:
    """递归合并 update 到 base（原地修改）。"""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def get_config_for_response(config: dict) -> dict:
    """返回前端展示用的配置（隐藏授权码等敏感字段）。"""
    email = dict(config.get("email", {}))
    email["sender_auth"] = "****" if email.get("sender_auth") else ""

    sms = dict(config.get("sms", {}))
    sms["access_key_secret"] = "****" if sms.get("access_key_secret") else ""

    return {
        "email": email,
        "sms": sms,
        "sms_template": config.get("sms", {}).get("template_content") or SMS_TEMPLATE,
        "sms_template_vars": SMS_TEMPLATE_VARS,
        "check_days": config.get("check_days", [1, 3, 7]),
        "data_source": config.get("data_source", "json"),
        "last_check": config.get("last_check"),
        "last_result": config.get("last_result"),
    }


def load_persons_from_json(json_path: str = JSON_PATH) -> list[dict]:
    """从 extraction_results.json 加载全部人员（含完整字段）"""
    if not os.path.exists(json_path):
        return []

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    persons = []
    for record in data:
        file_name = record.get("file_name", "")
        insurance_company = record.get("insurance_company", "")
        policy_number = record.get("policy_number", "")
        overall_end = record.get("overall_end_date", "")

        for p in record.get("insured_persons", []):
            person = {
                "name": p.get("name", ""),
                "id_number": p.get("id_number", ""),
                "id_type": p.get("id_type", "身份证"),
                "birth_date": p.get("birth_date", ""),
                "company": p.get("company", ""),
                "modification_type": p.get("modification_type", "增保"),
                "start_date": p.get("start_date", "") or record.get("overall_start_date", ""),
                "end_date": p.get("end_date", "") or overall_end,
                "job_title": p.get("job_title", p.get("occupation_class", "")),
                "insurance_company": insurance_company,
                "policy_number": policy_number,
                "file_name": file_name,
            }
            # 只保留 end_date 不为空的行
            if person["end_date"]:
                persons.append(person)

    return persons


def find_expiring_tomorrow(persons: list[dict]) -> list[dict]:
    """筛选明天到期的人员"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return [p for p in persons if p["end_date"] == tomorrow]


def build_email_html(persons: list[dict], target_date: str, email_config: Optional[dict] = None) -> str:
    """构建 HTML 表格邮件内容（标题/副标题/页脚均读 email_config，缺省用默认模板）"""
    ec = email_config or {}
    title = ec.get("title") or EMAIL_TITLE_DEFAULT
    subtitle = render_template(ec.get("subtitle_template") or EMAIL_SUBTITLE_DEFAULT, target_date=target_date)
    footer = ec.get("footer") or EMAIL_FOOTER_DEFAULT

    if not persons:
        return f"<p>暂无（{target_date}）到期的保险人员。</p>"

    rows_html = ""
    for i, p in enumerate(persons, 1):
        rows_html += "<tr>"
        rows_html += f"<td>{i}</td>"
        for _, key in ALL_FIELDS:
            value = p.get(key, "")
            # 到期日期标红
            if key == "end_date":
                rows_html += f'<td style="color:#e53e3e;font-weight:bold">{value}</td>'
            else:
                rows_html += f"<td>{value}</td>"
        rows_html += "</tr>\n"

    header_html = "<tr><th>#</th>"
    for label, _ in ALL_FIELDS:
        header_html += f"<th>{label}</th>"
    header_html += "</tr>"

    total = len(persons)
    company_names = set(p.get("company", "") for p in persons)
    companies = "、".join(c for c in company_names if c)

    return f"""
    <html><body style="font-family:'Microsoft YaHei',Arial,sans-serif;background:#f5f5f5;padding:20px">
    <div style="max-width:1200px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1)">
        <div style="background:linear-gradient(135deg,#e53e3e,#c53030);color:white;padding:20px 24px">
            <h2 style="margin:0">{title}</h2>
            <p style="margin:4px 0 0;opacity:0.9">{subtitle}</p>
        </div>
        <div style="padding:16px 24px">
            <p>涉及公司：{companies or '—'}</p>
            <p>到期人数：<b style="color:#e53e3e">{total} 人</b></p>
            <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:12px">
                <thead>
                    {header_html}
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        <div style="background:#fafafa;padding:12px 24px;color:#999;font-size:11px">
            {footer} &mdash; {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
    </body></html>
    """


def send_reminder_email(
    persons: list[dict],
    target_date: str,
    email_config: Optional[dict] = None,
) -> dict:
    """发送到期提醒邮件

    Args:
        persons: 到期人员列表
        target_date: 目标到期日期
        email_config: 邮件配置，默认从配置文件读取

    Returns:
        dict: {"success": bool, "message": str}
    """
    if not persons:
        return {"success": True, "message": f"{target_date} 无到期人员，跳过发送"}

    if email_config is None:
        cfg = load_config()
        email_config = cfg.get("email", {})

    if not email_config.get("enabled", True):
        return {"success": False, "message": "邮件通知已禁用，请在配置中启用"}

    sender = email_config.get("sender_email", "")
    password = email_config.get("sender_auth", "")
    recipients = email_config.get("recipient_emails", [])
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]
    smtp_host = email_config.get("smtp_host", "smtp.qq.com")
    smtp_port = email_config.get("smtp_port", 465)

    if not sender or not password or not recipients:
        return {"success": False, "message": "邮箱配置不完整，请填写发件人/授权码/收件人"}

    subject = render_template(
        email_config.get("subject_template") or EMAIL_SUBJECT_DEFAULT,
        target_date=target_date,
        total=len(persons),
    )

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    html_body = build_email_html(persons, target_date, email_config)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        log_send(
            channel="expiry_reminder", kind="email", to=recipients,
            person_count=len(persons),
            person_names=[p.get("name", "") for p in persons],
            subject=subject, success=True,
            result=f"已发送至 {len(recipients)} 个收件人，共 {len(persons)} 人到期",
            extra={"target_date": target_date},
        )
        return {"success": True, "message": f"已发送提醒邮件到 {', '.join(recipients)}，{len(persons)} 人到期"}
    except smtplib.SMTPAuthenticationError:
        log_send(
            channel="expiry_reminder", kind="email", to=recipients,
            person_count=len(persons),
            person_names=[p.get("name", "") for p in persons],
            subject=subject, success=False, result="SMTP 认证失败",
        )
        return {"success": False, "message": f"SMTP认证失败，请检查授权码是否正确"}
    except smtplib.SMTPConnectError:
        log_send(
            channel="expiry_reminder", kind="email", to=recipients,
            person_count=len(persons),
            person_names=[p.get("name", "") for p in persons],
            subject=subject, success=False, result=f"无法连接 SMTP 服务器 {smtp_host}:{smtp_port}",
        )
        return {"success": False, "message": f"无法连接SMTP服务器 {smtp_host}:{smtp_port}"}
    except Exception as e:
        log_send(
            channel="expiry_reminder", kind="email", to=recipients,
            person_count=len(persons),
            person_names=[p.get("name", "") for p in persons],
            subject=subject, success=False, result="SMTP 异常",
            error=str(e),
        )
        return {"success": False, "message": f"邮件发送失败: {e}"}


def run_reminder_check(config: Optional[dict] = None) -> dict:
    """执行一次到期提醒检查

    Args:
        config: 提醒配置，默认从配置文件读取

    Returns:
        dict: 执行结果
    """
    if config is None:
        config = load_config()

    data_source = config.get("data_source", "json")
    check_days = config.get("check_days", [1])
    email_config = config.get("email", {})

    if data_source == "excel":
        persons = _load_persons_from_excel()
    else:
        persons = load_persons_from_json()

    today = datetime.now()
    results = []
    total_expiring = 0

    for days_ahead in sorted(check_days):
        target_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        expiring = [p for p in persons if p["end_date"] == target_date]

        if expiring:
            if email_config.get("enabled", True):
                email_result = send_reminder_email(expiring, target_date, email_config)
            else:
                email_result = {"success": False, "message": "邮件通知已禁用"}

            results.append({
                "days_ahead": days_ahead,
                "target_date": target_date,
                "expiring_count": len(expiring),
                "email_sent": email_result.get("success", False),
                "email_message": email_result.get("message", ""),
            })
            total_expiring += len(expiring)
        else:
            results.append({
                "days_ahead": days_ahead,
                "target_date": target_date,
                "expiring_count": 0,
                "email_sent": False,
                "email_message": f"{target_date} 无到期人员",
            })

    check_date = today.strftime("%Y-%m-%d")

    result = {
        "check_date": check_date,
        "total_in_system": len(persons),
        "total_expiring": total_expiring,
        "results": results,
        "success": True,
        "message": f"检查完成，共 {total_expiring} 人到期",
    }

    # 保存执行记录到配置
    config["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    config["last_result"] = {
        "check_date": check_date,
        "total_in_system": len(persons),
        "total_expiring": total_expiring,
        "results": results,
    }
    save_config(config)

    return result


# ============ 到期提醒（数据库数据源） ============

# 到期提醒邮件的展示字段（贴合数据库字段名）
EXPIRY_FIELDS = [
    ("姓名", "name"),
    ("证件号码", "id_number"),
    ("所属公司", "company"),
    ("岗位名称", "job_title"),
    ("起始时间", "start_date"),
    ("起止时间", "end_date"),
    ("保险公司", "insurance_company"),
    ("保单号", "policy_number"),
]


def find_expiring_from_db(ahead_days: int) -> list[dict]:
    """从数据库查询「ahead_days 天内到期」的人员（状态正常）

    语义：查询到期日在 [今天, 今天+ahead_days] 范围内的人员，
    即"未来 N 天内即将到期"，而非"恰好第 N 天到期"。
    这样还有 1 天、2 天到期的人也会被一并提醒，避免漏掉。

    Args:
        ahead_days: 提前天数，如 3 表示查询"未来 3 天内到期"（今天 ≤ end_date ≤ 今天+3天）

    Returns:
        即将到期的人员列表（数据库记录）
    """
    from insurance_agent.infrastructure import database as db

    if ahead_days is None or ahead_days < 0:
        ahead_days = 0

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    deadline = (now + timedelta(days=ahead_days)).strftime("%Y-%m-%d")

    persons = db.get_insurance_personnel()
    return [
        p for p in persons
        if (p.get("status") or "") == "正常"
        and today <= (p.get("end_date") or "") <= deadline
    ]


def build_expiry_email_html(persons: list[dict], target_date: str, ahead_days: int, email_config: Optional[dict] = None) -> str:
    """构建到期提醒邮件 HTML（提示"未来 N 天内到期，请及时续保"）标题/副标题/页脚读 email_config"""
    ec = email_config or {}
    title = ec.get("expiry_title") or EXPIRY_TITLE_DEFAULT
    days_text = "今天" if ahead_days == 0 else f"未来 {ahead_days} 天内"
    subtitle = render_template(
        ec.get("expiry_subtitle_template") or EXPIRY_SUBTITLE_DEFAULT,
        days_text=days_text,
        target_date=target_date,
    )
    footer = ec.get("footer") or EMAIL_FOOTER_DEFAULT

    if not persons:
        return f"<p>暂无{days_text}（截至 {target_date}）到期的人员保险。</p>"

    rows_html = ""
    for i, p in enumerate(persons, 1):
        rows_html += "<tr>"
        rows_html += f"<td>{i}</td>"
        for _, key in EXPIRY_FIELDS:
            value = p.get(key, "") or ""
            if key == "end_date":
                rows_html += f'<td style="color:#e53e3e;font-weight:bold">{value}</td>'
            else:
                rows_html += f"<td>{value}</td>"
        rows_html += "</tr>\n"

    header_html = "<tr><th>#</th>"
    for label, _ in EXPIRY_FIELDS:
        header_html += f"<th>{label}</th>"
    header_html += "</tr>"

    total = len(persons)
    company_names = {p.get("company", "") for p in persons}
    companies = "、".join(c for c in company_names if c)

    return f"""
    <html><body style="font-family:'Microsoft YaHei',Arial,sans-serif;background:#f5f5f5;padding:20px">
    <div style="max-width:1200px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1)">
        <div style="background:linear-gradient(135deg,#ed8936,#dd6b20);color:white;padding:20px 24px">
            <h2 style="margin:0">{title}</h2>
            <p style="margin:4px 0 0;opacity:0.9">{subtitle}</p>
        </div>
        <div style="padding:16px 24px">
            <p>涉及公司：{companies or '—'}</p>
            <p>即将到期人数：<b style="color:#ed8936">{total} 人</b></p>
            <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:12px">
                <thead>
                    {header_html}
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        <div style="background:#fafafa;padding:12px 24px;color:#999;font-size:11px">
            {footer} &mdash; {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
    </body></html>
    """


def _send_expiry_email(
    persons: list[dict],
    target_date: str,
    ahead_days: int,
    email_config: dict,
) -> dict:
    """发送到期提醒邮件"""
    sender = email_config.get("sender_email", "")
    password = email_config.get("sender_auth", "")
    recipients = email_config.get("recipient_emails", [])
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]

    if not sender or not password or not recipients:
        return {"success": False, "message": "邮箱配置不完整，请填写发件人/授权码/收件人"}

    smtp_host = email_config.get("smtp_host", "smtp.qq.com")
    smtp_port = email_config.get("smtp_port", 465)

    days_text = "今天" if ahead_days == 0 else f"未来 {ahead_days} 天内"
    subject = render_template(
        email_config.get("expiry_subject_template") or EXPIRY_SUBJECT_DEFAULT,
        days_text=days_text,
        total=len(persons),
    )

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(build_expiry_email_html(persons, target_date, ahead_days, email_config), "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        log_send(
            channel="expiry_reminder", kind="email", to=recipients,
            person_count=len(persons),
            person_names=[p.get("name", "") for p in persons],
            subject=subject, success=True,
            result=f"已发送至 {len(recipients)} 个收件人，共 {len(persons)} 人即将到期",
            extra={"target_date": target_date, "ahead_days": ahead_days},
        )
        return {"success": True, "message": f"已发送到期提醒邮件到 {', '.join(recipients)}，{len(persons)} 人即将到期"}
    except smtplib.SMTPAuthenticationError:
        log_send(
            channel="expiry_reminder", kind="email", to=recipients,
            person_count=len(persons),
            person_names=[p.get("name", "") for p in persons],
            subject=subject, success=False, result="SMTP 认证失败",
            extra={"target_date": target_date, "ahead_days": ahead_days},
        )
        return {"success": False, "message": "SMTP认证失败，请检查授权码是否正确"}
    except smtplib.SMTPConnectError:
        log_send(
            channel="expiry_reminder", kind="email", to=recipients,
            person_count=len(persons),
            person_names=[p.get("name", "") for p in persons],
            subject=subject, success=False,
            result=f"无法连接 SMTP 服务器 {smtp_host}:{smtp_port}",
            extra={"target_date": target_date, "ahead_days": ahead_days},
        )
        return {"success": False, "message": f"无法连接SMTP服务器 {smtp_host}:{smtp_port}"}
    except Exception as e:
        log_send(
            channel="expiry_reminder", kind="email", to=recipients,
            person_count=len(persons),
            person_names=[p.get("name", "") for p in persons],
            subject=subject, success=False, result="SMTP 异常",
            error=str(e),
            extra={"target_date": target_date, "ahead_days": ahead_days},
        )
        return {"success": False, "message": f"邮件发送失败: {e}"}


def run_expiry_check(ahead_days: Optional[int] = None, config: Optional[dict] = None) -> dict:
    """执行一次到期提醒检查（定时任务回调入口）

    查询「ahead_days 天内」即将到期的人员保险，如有则发送**邮件**提醒续保。
    按用户最新要求：到期提醒**仅发邮件**到��息提醒配置中的固定收件人邮箱，
    **不发送手机短信**。

    Args:
        ahead_days: 提前天数（默认从配置 expiry_ahead_days 读取）
        config: 提醒配置（默认从配置文件读取）

    Returns:
        dict: 执行结果（不再含 sms 字段）
    """
    if config is None:
        config = load_config()

    if ahead_days is None:
        ahead_days = int(config.get("expiry_ahead_days", 3))

    email_config = config.get("email", {})

    deadline = (datetime.now() + timedelta(days=ahead_days)).strftime("%Y-%m-%d")
    expiring = find_expiring_from_db(ahead_days)

    result = {
        "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ahead_days": ahead_days,
        "target_date": deadline,
        "expiring_count": len(expiring),
        "expiring_persons": expiring,
        "email": None,
    }

    days_text = "今天" if ahead_days == 0 else f"未来 {ahead_days} 天内"

    if not expiring:
        result["success"] = True
        result["message"] = f"{days_text}（截至 {deadline}）无即将到期人员，无需提醒"
        result["email"] = {"success": True, "message": "无即���到期人员"}
        return result

    if not email_config.get("enabled", True):
        result["success"] = False
        result["message"] = f"存在 {len(expiring)} 人即将到期，但邮件通知已禁用"
        result["email"] = {"success": False, "message": "邮件通知已禁用"}
        return result

    email_result = _send_expiry_email(expiring, deadline, ahead_days, email_config)
    result["email"] = email_result
    result["success"] = email_result.get("success", False)
    result["message"] = email_result.get("message", "")

    # 保存执行记录（仅含邮件结果；到期提醒按要求不发短信）
    config["last_expiry_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    config["last_expiry_result"] = {
        "ahead_days": ahead_days,
        "target_date": deadline,
        "expiring_count": len(expiring),
        "email_sent": email_result.get("success", False),
        "email_message": email_result.get("message", ""),
    }
    save_config(config)

    return result


def _load_persons_from_excel() -> list[dict]:
    """从 Excel 模板加载人员（字段较少的兜底方案）"""
    if not os.path.exists(EXCEL_PATH):
        return []

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active

    persons = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:  # 跳过空行
            continue
        # Excel模板字段：姓名/证件号码/年龄/打卡项目/所属班组/所属公司/劳务分类
        names = ["name", "id_number", "age", "punch_item", "team", "company", "labor_type"]
        person = {}
        for i, val in enumerate(row[:7]):
            person[names[i]] = str(val) if val is not None else ""
        if person.get("name"):
            persons.append(person)
    wb.close()
    return persons


# ============ 命令行入口 ============
if __name__ == "__main__":
    import sys

    source = sys.argv[1] if len(sys.argv) > 1 else None
    if source:
        config = load_config()
        config["data_source"] = source
        result = run_reminder_check(config=config)
    else:
        result = run_reminder_check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
