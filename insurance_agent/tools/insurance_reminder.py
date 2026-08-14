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

# ============ 默认配置 (首次使用时写入配置文件) ============
DEFAULT_CONFIG = {
    "email": {
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "sender_email": "1337382541@qq.com",
        "sender_auth": "qwutucsktjwobaha",
        "recipient_emails": ["1130530657@qq.com"],
        "enabled": True,
    },
    "sms": {
        "enabled": False,               # 短信通知启用开关
        "provider": "aliyun",           # aliyun / tencent
        "access_key_id": "",            # 阿里云 AccessKey ID / 腾讯云 SecretId
        "access_key_secret": "",        # 阿里云 AccessKey Secret / 腾讯云 SecretKey
        "sdk_app_id": "",               # 腾讯云专用 SDKAppID
        "sign_name": "",                # 短信签名（需服务商审核）
        "template_code": "",            # 短信模板 Code（需服务商审核）
        "phone_numbers": [],            # 接收手机号列表
    },
    "check_days": [1, 3, 7],  # 提前1/3/7天检查
    "data_source": "json",
}

# 数据源路径（统一路径配置，支持 Docker 部署环境变量覆盖）
from insurance_agent.infrastructure.paths import PROJECT_ROOT, REMINDER_CONFIG_PATH
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


def build_email_html(persons: list[dict], target_date: str) -> str:
    """构建 HTML 表格邮件内容"""
    if not persons:
        return f"<p>暂无明天（{target_date}）到期的保险人员。</p>"

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
            <h2 style="margin:0">⚠️ 保险到期提醒</h2>
            <p style="margin:4px 0 0;opacity:0.9">以下人员保险将于 <b>{target_date}</b> 到期，请及时处理续保</p>
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
            本邮件由保险单识别系统自动发送 &mdash; {datetime.now().strftime('%Y-%m-%d %H:%M')}
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

    subject = f"⚠️ 保险到期提醒 — {target_date} 到期 {len(persons)} 人"

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    html_body = build_email_html(persons, target_date)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        return {"success": True, "message": f"已发送提醒邮件到 {', '.join(recipients)}，{len(persons)} 人到期"}
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": f"SMTP认证失败，请检查授权码是否正确"}
    except smtplib.SMTPConnectError:
        return {"success": False, "message": f"无法连接SMTP服务器 {smtp_host}:{smtp_port}"}
    except Exception as e:
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
