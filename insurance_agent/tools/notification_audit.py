"""通知发送审计日志

目的：记录每一次"打卡无正常保险"的短信和邮件发送（成功/失败），方便跟踪
通知是否触达真实项目经理，防止「生产模式下悄悄漏发」类问题。

设计原则：
- 单一写入入口（log_send），所有发送模块都通过它记录，避免散落 print
- 追加写 JSON Lines（每行一条 JSON），便于解析和归档
- 日志路径与配置分离：审计日志写到 C:\\insurance-automation\\notification_audit.jsonl
  （不写到 data/ 下，避免和保险数据混在一起）
- 提供查询 / 导出 / 清理接口，供前端「通知审计」标签页使用

字段：
- ts: ISO 时间戳
- channel: realtime / daily_check / summary_morning / summary_afternoon / expiry_reminder / test_manual
- kind: sms / email
- to: 收件人（手机号或邮箱列表，统一为 list）
- project: 项目名（可空）
- manager: 经理姓名（可空）
- person_count: 涉及未参保/到期人员数
- person_names: 涉及人员姓名（前 5 个）
- subject: 邮件主题（仅 email）
- success: True / False
- result: 发送器返回的消息（成功条数 / 失败原因）
- error: 异常堆栈首行（仅失败时记录）
- test_mode: 是否测试模式（true 时也记录，但标记出来）
- extra: 其它自定义上下文（dict）

读取接口：
- read_audit(limit, channel, kind, date_from, date_to) → list[dict]
- count_audit(channel, kind, date) → int
- clear_audit(older_than_days) → 删除的条数
"""

import json
import os
import threading
from datetime import datetime, timedelta
from typing import Optional

AUDIT_LOG_PATH = r"C:\insurance-automation\notification_audit.jsonl"
_LOCK = threading.Lock()
_MAX_LINES = 50000  # 防止无限增长；超出时自动滚动


def _ensure_dir():
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_json_dumps(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


def log_send(
    channel: str,
    kind: str,
    to,
    *,
    project: str = "",
    manager: str = "",
    person_count: int = 0,
    person_names=None,
    subject: str = "",
    success: bool = True,
    result: str = "",
    error: str = "",
    test_mode: bool = False,
    extra: Optional[dict] = None,
) -> dict:
    """记录一次发送审计日志。

    Args:
        channel: realtime / daily_check / summary_morning / summary_afternoon /
                 expiry_reminder / test_manual
        kind: "sms" / "email"
        to: 收件人（list 或 str；统一存为 list）
    Returns:
        dict: 写入的审计记录（便于调用方回传）
    """
    if isinstance(to, str):
        to_list = [to]
    elif isinstance(to, (list, tuple)):
        to_list = [str(x) for x in to if str(x).strip()]
    else:
        to_list = [str(to)] if to else []

    record = {
        "ts": _now_iso(),
        "channel": channel,
        "kind": kind,
        "to": to_list,
        "project": project,
        "manager": manager,
        "person_count": int(person_count or 0),
        "person_names": list(person_names or [])[:5],
        "subject": subject,
        "success": bool(success),
        "result": str(result)[:500],  # 防止单条记录过大
        "error": str(error)[:500],
        "test_mode": bool(test_mode),
        "extra": extra or {},
    }

    line = _safe_json_dumps(record)
    with _LOCK:
        try:
            _ensure_dir()
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # 审计失败不能阻塞业务；用 print 兜底
            try:
                print(f"[notification_audit] 写审计日志失败: line={line[:200]}")
            except Exception:
                pass

    # 滚动：超过上限则把前 20% 移到 .old 文件（保留最新 80%）
    try:
        _maybe_rotate()
    except Exception:
        pass

    return record


def _maybe_rotate():
    """超过 _MAX_LINES 时滚动：把超出部分写到 .old 文件。"""
    if not os.path.exists(AUDIT_LOG_PATH):
        return
    try:
        with open(AUDIT_LOG_PATH, "rb") as f:
            lines = f.readlines()
        if len(lines) <= _MAX_LINES:
            return
        keep = int(_MAX_LINES * 0.8)
        old_lines = lines[: len(lines) - keep]
        new_lines = lines[-keep:]
        old_path = AUDIT_LOG_PATH + ".old"
        with open(old_path, "ab") as f:
            f.writelines(old_lines)
        with open(AUDIT_LOG_PATH, "wb") as f:
            f.writelines(new_lines)
    except Exception:
        pass


def read_audit(
    limit: int = 200,
    channel: Optional[str] = None,
    kind: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    only_failures: bool = False,
) -> list:
    """读取最近的审计记录（倒序，新→旧）。"""
    if not os.path.exists(AUDIT_LOG_PATH):
        return []

    rows = []
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if channel and rec.get("channel") != channel:
                    continue
                if kind and rec.get("kind") != kind:
                    continue
                if only_failures and rec.get("success"):
                    continue
                ts = rec.get("ts", "")
                if date_from and ts < date_from:
                    continue
                if date_to and ts > date_to:
                    continue
                rows.append(rec)
    except Exception:
        return []

    rows.reverse()  # 最新的在前
    return rows[:limit]


def count_audit(channel: Optional[str] = None, date: Optional[str] = None) -> int:
    """统计指定条件下的审计记录数。"""
    if not os.path.exists(AUDIT_LOG_PATH):
        return 0
    n = 0
    try:
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if channel and rec.get("channel") != channel:
                    continue
                if date and not rec.get("ts", "").startswith(date):
                    continue
                n += 1
    except Exception:
        pass
    return n


def clear_audit(older_than_days: int = 0) -> int:
    """清理审计日志。

    Args:
        older_than_days: 0 = 清空全部；>0 = 仅清理 N 天前的
    Returns:
        删除的记录条数
    """
    if not os.path.exists(AUDIT_LOG_PATH):
        return 0
    with _LOCK:
        try:
            if older_than_days <= 0:
                # 全部清空
                with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                n = sum(1 for ln in lines if ln.strip())
                with open(AUDIT_LOG_PATH, "w", encoding="utf-8"):
                    pass
                # 同步清理 .old
                old = AUDIT_LOG_PATH + ".old"
                if os.path.exists(old):
                    try:
                        os.remove(old)
                    except Exception:
                        pass
                return n

            # 仅清理 N 天前的
            cutoff = (datetime.now() - timedelta(days=older_than_days)).strftime("%Y-%m-%d")
            kept = []
            removed = 0
            with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line_s = line.strip()
                    if not line_s:
                        continue
                    try:
                        rec = json.loads(line_s)
                    except Exception:
                        continue
                    if rec.get("ts", "") < cutoff:
                        removed += 1
                    else:
                        kept.append(line)
            with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(kept)
            return removed
        except Exception:
            return 0


def stats_today() -> dict:
    """返回今日（按服务器本地日期）的发送统计。"""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = read_audit(limit=10000, date_from=today + " 00:00:00", date_to=today + " 23:59:59")
    total = len(rows)
    sms = [r for r in rows if r.get("kind") == "sms"]
    email = [r for r in rows if r.get("kind") == "email"]
    succ = [r for r in rows if r.get("success")]
    fail = [r for r in rows if not r.get("success")]
    test = [r for r in rows if r.get("test_mode")]
    by_channel = {}
    for r in rows:
        ch = r.get("channel") or "unknown"
        by_channel.setdefault(ch, 0)
        by_channel[ch] += 1
    return {
        "date": today,
        "total": total,
        "sms_count": len(sms),
        "email_count": len(email),
        "success_count": len(succ),
        "failure_count": len(fail),
        "test_mode_count": len(test),
        "by_channel": by_channel,
    }