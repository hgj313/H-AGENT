"""实时打卡事件消费引擎（保险管理AI助手）

解决「ERP 每产生一条打卡，智能体实时核对保险并通知」的需求。

架构（与 ERP 团队建议的 MQ 解耦一致）：
- 本模块是一个**进程内消息队列 + 后台消费者**（queue.Queue + daemon 线程）。
- ERP 侧把打卡事件推送进来有两种等价方式：
    1) HTTP 适配入口：POST /api/punch/events（server.py 提供）。ERP 或「MQ 桥接程序」
       订阅 ERP 的 MQ 后，转调此 HTTP 接口即可。这是当前可在沙箱直接测试的方式。
    2) 未来若要在智能体进程内直接消费 MQ，只需新增一个 MQ 订阅协程，把消息
       submit_punch_events() 即可，下游处理逻辑完全复用。
- 消费者用**滑动窗口批处理**：首个事件到达后最多等待 batch_window_seconds，
  期间到达的事件一并处理。这样既保证「实时」（秒级），又能在多个打卡机同时
  打卡（瞬时大量事件）时把 N 次「入库+查保险+发通知」合并成少数几次，
  显著降低 DB/保险查询与短信/邮件的调用量。
- 每条事件只做一次「按身份证号查有效保单」，整批共享一次保险快照，O(批大小)。
- 人员去重：同一人同一天仅通知一次（realtime_notified_today），避免一个人
  上下班多次打卡被反复提醒；生产模式下额外对「项目经理手机号」做每日去重，
  避免同一经理当日收到多封短信。

通知路由（测试阶段）：
- notification_test_mode=true 时，所有短信统一发到 test_sms_phone，
  所有邮件（含保险管理人员汇总）统一发到 test_email，绝不触达真实项目人员。
- 切回生产时把 notification_test_mode 改为 false，即恢复按项目经理真实联系方式发送。
"""

import logging
import queue
import smtplib
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from insurance_agent.infrastructure import database as db
from insurance_agent.tools.insurance_reminder import (
    load_config,
    save_config,
    build_sms_messages,
)
from insurance_agent.tools.daily_check_service import build_coverage_email_html
from insurance_agent.tools.sms_sender import send_sms
from insurance_agent.tools.feishu_webhook_pusher import push_uninsured_person
from insurance_agent.tools.notification_audit import log_send

logger = logging.getLogger(__name__)

REALTIME_LOG = r"C:\insurance-automation\realtime.log"
MANAGER_REFRESH_SEC = 900  # 经理缓存刷新间隔（15 分钟）

_QUEUE: "queue.Queue" = queue.Queue()
_STOP = threading.Event()
_STARTED = False
_WORKER = None
_SESSION_MANAGER = None
_MANAGER_CACHE: dict = {}
_MANAGER_LOCK = threading.Lock()
_STATS = {
    "accepted": 0,
    "batches": 0,
    "last_batch_at": None,
    "last_processed": 0,
    "errors": 0,
    "manager_cache_size": 0,
    "started_at": None,
}


def _log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(REALTIME_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    logger.info("[realtime] %s", msg)


# ============ 事件规范化 ============

def _pick(raw: dict, *keys, default=""):
    for k in keys:
        v = raw.get(k)
        # 过滤：None / 空字符串 / 字符串 "undefined" / "null" / "NaN"
        # ERP 端常把空值塞成字符串 "undefined"（前端 bug），不过滤会原样入库
        if v is None:
            continue
        if isinstance(v, str) and v.strip().lower() in ("", "undefined", "null", "nan"):
            continue
        return v
    return default


def _normalize(raw: dict) -> dict:
    """把 ERP 原始打卡事件（兼容驼峰/蛇形命名）规范化为 upsert 所需字段。"""
    if not isinstance(raw, dict):
        return {}
    return {
        "id": _pick(raw, "id", "erp_id", "erpId"),
        "memberId": _pick(raw, "memberId", "member_id"),
        "memberName": _pick(raw, "memberName", "member_name", "name"),
        "identificationNumber": _pick(
            raw, "identificationNumber", "identification_number",
            "id_number", "idNumber",
        ),
        "age": _pick(raw, "age"),
        "projectName": _pick(raw, "projectName", "project_name"),
        "teamName": _pick(raw, "teamName", "team_name"),
        "supplierName": _pick(raw, "supplierName", "supplier_name"),
        "categoryName": _pick(raw, "categoryName", "category_name"),
        "examinationStatusName": _pick(
            raw, "examinationStatusName", "examination_status_name", "examination_status",
        ),
        "telephone": _pick(raw, "telephone", "phone"),
        # 项目经理联系方式（ERP 实时消息体携带，方便跨项目跨天去重后仍能直接拿到联系人）
        "projectManager": _pick(
            raw, "projectManager", "project_manager", "projectManagerName",
            "project_manager_name",
        ),
        "managerPhone": _pick(
            raw, "managerPhone", "manager_phone", "projectManagerPhone",
            "project_manager_phone",
        ),
        "managerEmail": _pick(
            raw, "managerEmail", "manager_email", "projectManagerEmail",
            "project_manager_email",
        ),
        "punchTime": _pick(
            raw, "punchTime", "punch_time", "punchtime", "punchDateTime",
            "firstPunchTime", "lastPunchTime",
            "clockTime", "signTime", "signInTime", "attendTime",
            "checkInTime", "checkinTime", "打卡时间", "打卡日期",
        ),
    }


# ============ 经理解析（缓存 + DB 回退） ============

def _refresh_manager_cache():
    if _SESSION_MANAGER is None:
        return
    try:
        from insurance_agent.tools import coverage_check
        client = coverage_check.ERPClient(_SESSION_MANAGER)
        mgr = coverage_check.build_manager_map(client)
        if mgr:
            with _MANAGER_LOCK:
                _MANAGER_CACHE.update(mgr)
            _STATS["manager_cache_size"] = len(_MANAGER_CACHE)
            _log(f"经理缓存刷新成功：{len(_MANAGER_CACHE)} 个项目")
    except Exception as e:  # noqa: BLE001
        _log(f"经理缓存刷新失败（保留旧缓存）: {e}")


def _resolve_manager(project_name: str) -> dict:
    if not project_name:
        return {}
    with _MANAGER_LOCK:
        if project_name in _MANAGER_CACHE:
            return _MANAGER_CACHE[project_name]
    # 回退：从已有打卡记录取该项目的经理联系方式
    try:
        row = db.get_manager_info_by_project(project_name)
        if row:
            with _MANAGER_LOCK:
                _MANAGER_CACHE[project_name] = row
            return row
    except Exception as e:  # noqa: BLE001
        _log(f"经理回退查询失败: {e}")
    return {}


# ============ 通知发送 ============

def _send_email_smtp(recipients: list, subject: str, html: str, email_config: dict, *, channel: str = "realtime", project: str = "", manager: str = "", person_count: int = 0, person_names=None, test_mode: bool = False) -> bool:
    recipients = [r.strip() for r in (recipients or []) if str(r).strip()]
    if not recipients:
        return False
    sender = email_config.get("sender_email", "")
    password = email_config.get("sender_auth", "")
    if not sender or not password:
        _log("邮件发送跳过：发件人配置不完整")
        # 审计：发送失败（配置缺失）
        log_send(
            channel=channel, kind="email", to=recipients,
            project=project, manager=manager, person_count=person_count,
            person_names=person_names, subject=subject, success=False,
            result="发件人配置不完整", test_mode=test_mode,
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
        # 审计：发送成功
        log_send(
            channel=channel, kind="email", to=recipients,
            project=project, manager=manager, person_count=person_count,
            person_names=person_names, subject=subject, success=True,
            result=f"已发送至 {len(recipients)} 个收件人", test_mode=test_mode,
        )
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"邮件发送失败 -> {recipients}: {e}")
        # 审计：发送失败
        log_send(
            channel=channel, kind="email", to=recipients,
            project=project, manager=manager, person_count=person_count,
            person_names=person_names, subject=subject, success=False,
            result="SMTP 异常", error=str(e), test_mode=test_mode,
        )
        return False


def _get_notified_ids(cfg: dict, punch_date: str) -> set:
    state = cfg.get("realtime_notified_today") or {}
    if state.get("punch_date") == punch_date:
        return set(state.get("ids", []))
    return set()


def _send_realtime_notifications(new_persons: list, punch_date: str, cfg: dict):
    """对一个批处理窗口内新发现的未参保人员发送通知（就地修改 cfg，由调用方统一保存）。

    测试模式：所有短信→test_sms_phone，所有邮件→test_email（含保险管理人员汇总）。
    生产模式：按项目经理真实联系方式发送；并对经理手机号做每日去重。
    """
    test_mode = bool(cfg.get("notification_test_mode", False))
    test_phone = (cfg.get("test_sms_phone") or "").strip()
    test_email = (cfg.get("test_email") or "").strip()
    email_config = cfg.get("email", {}) or {}
    sms_config = cfg.get("sms", {}) or {}

    by_proj: dict = defaultdict(list)
    for p in new_persons:
        by_proj[p.get("project_name") or "未知项目"].append(p)

    # ---------- 短信：每项目一条 ----------
    sms_results = []
    if sms_config.get("enabled", False):
        messages_by_project = {
            m["project"]: m for m in build_sms_messages(new_persons, "project_name")
        }
        sent_state = cfg.get("realtime_sms_sent_today") or {}
        already = (
            set(sent_state.get("phones", []))
            if sent_state.get("punch_date") == punch_date
            else set()
        )
        newly_sent = []
        for proj, persons in by_proj.items():
            msg = messages_by_project.get(proj)
            if not msg:
                continue
            if test_mode:
                phone = test_phone
            else:
                phone = (persons[0].get("manager_phone") or "").strip()
            if not phone:
                # 审计：无手机号 → 跳过
                log_send(
                    channel="realtime", kind="sms", to=[],
                    project=proj, manager=persons[0].get("project_manager", ""),
                    person_count=len(persons),
                    person_names=[p.get("name", "") for p in persons],
                    subject=msg.get("project", ""),
                    success=False, result="无经理手机号，跳过发送",
                    test_mode=test_mode,
                )
                continue
            # 生产模式：同一经理手机号当日仅一条短信（避免多项目/多人反复打扰）
            if not test_mode and phone in already:
                sms_results.append({"project": proj, "phone": phone, "skipped": "per-phone dedup"})
                # 审计：dedup 跳过
                log_send(
                    channel="realtime", kind="sms", to=[phone],
                    project=proj, manager=persons[0].get("project_manager", ""),
                    person_count=len(persons),
                    person_names=[p.get("name", "") for p in persons],
                    subject=msg.get("project", ""),
                    success=False,
                    result=f"该手机号今日已发送，跳过（per-phone dedup）",
                    test_mode=test_mode,
                )
                continue
            c = dict(sms_config)
            c["phone_numbers"] = [phone]
            r = send_sms(c, [msg])
            r["project"] = proj
            r["phone"] = phone
            sms_results.append(r)
            # 审计：实际发送结果
            log_send(
                channel="realtime", kind="sms", to=[phone],
                project=proj, manager=persons[0].get("project_manager", ""),
                person_count=len(persons),
                person_names=[p.get("name", "") for p in persons],
                subject=msg.get("project", ""),
                success=bool(r.get("success")),
                result=r.get("message", ""),
                error="" if r.get("success") else r.get("message", ""),
                test_mode=test_mode,
            )
            if r.get("success") and not test_mode:
                newly_sent.append(phone)
        if newly_sent:
            merged = list(already | set(newly_sent))
            cfg["realtime_sms_sent_today"] = {
                "punch_date": punch_date,
                "phones": merged,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
    else:
        _log("短信未启用，跳过短信发送")

    # ---------- 邮件：每项目经理一封（仅自己项目人员） ----------
    # 注意：保险管理人员汇总邮件不在此发送，改为定时汇总（每天 9:00 + 16:30）
    # 由 uninsured_summary.run_uninsured_summary() 调度发送，避免邮件刷屏。
    email_results = []
    if email_config.get("enabled", True):
        for proj, persons in by_proj.items():
            if test_mode:
                recips = [test_email] if test_email else []
            else:
                recips = [ (persons[0].get("manager_email") or "").strip() ]
                recips = [r for r in recips if r]
            if not recips:
                continue
            subject = f"⚠️ 保险购买提醒 — {punch_date} 项目「{proj}」{len(persons)} 人未正常参保"
            html = build_coverage_email_html(persons, punch_date, f"项目 {proj}")
            ok = _send_email_smtp(
                recips, subject, html, email_config,
                channel="realtime",
                project=proj,
                manager=persons[0].get("project_manager", ""),
                person_count=len(persons),
                person_names=[p.get("name", "") for p in persons],
                test_mode=test_mode,
            )
            email_results.append({"project": proj, "to": recips, "success": ok})
    else:
        _log("邮件未启用，跳过项目经理邮件")

    _log(
        f"实时通知发送完成： SMS={len(sms_results)} 封(成功"
        f"{sum(1 for r in sms_results if r.get('success'))}), "
        f"EMAIL={len(email_results)} 封(成功"
        f"{sum(1 for r in email_results if r.get('success'))}), "
        f"test_mode={test_mode}"
    )


# ============ 批处理核心 ============

def _process_events(events: list):
    if not events:
        return
    punch_date = datetime.now().strftime("%Y-%m-%d")
    norm = [_normalize(e) for e in events if isinstance(e, dict)]
    norm = [e for e in norm if e.get("identificationNumber")]
    if not norm:
        _log("本批无有效身份证号，跳过")
        return

    try:
        stored = db.upsert_punch_records(norm, punch_date)
    except Exception as e:  # noqa: BLE001
        _log(f"打卡入库失败（跳过本批）: {e}")
        return

    try:
        db.refresh_expired_status()
    except Exception:  # noqa: BLE001
        pass

    try:
        active = db.get_active_insurance_by_id()
    except Exception as e:  # noqa: BLE001
        _log(f"查询有效保单失败（跳过本批）: {e}")
        return

    seen = set()
    candidates = []
    for e in norm:
        idn = e["identificationNumber"]
        if idn in seen:
            continue
        seen.add(idn)
        if active.get(idn):
            continue  # 有正常状态保单，覆盖正常
        mgr = _resolve_manager(e.get("projectName", ""))
        candidates.append({
            "name": e.get("memberName", ""),
            "id_number": idn,
            "project_name": e.get("projectName", ""),
            "team_name": e.get("teamName", ""),
            "supplier_name": e.get("supplierName", ""),
            "category_name": e.get("categoryName", ""),
            "project_manager": mgr.get("project_manager", ""),
            "manager_phone": mgr.get("manager_phone", ""),
            "manager_email": mgr.get("manager_email", ""),
            "punch_time": e.get("punchTime", ""),  # 补：让飞书表格"打卡时间"列有数据
        })

    _STATS["last_processed"] = len(norm)

    if not candidates:
        _log(f"本批 {len(norm)} 条打卡均已正常参保，无需提醒")
        return

    # 人员按天去重：同一人同一天仅通知一次
    cfg = load_config()
    notified = _get_notified_ids(cfg, punch_date)
    new_persons = [p for p in candidates if p["id_number"] not in notified]
    if not new_persons:
        _log(f"本批 {len(candidates)} 名未参保人员今日已通知过，跳过重复提醒")
        return

    _log(
        f"本批入库 {stored} 条，发现 {len(candidates)} 名未参保，"
        f"其中 {len(new_persons)} 名为今日新增未通知："
        + "；".join(f"{p['name']}({p['project_name']})" for p in new_persons[:10])
        + ("…" if len(new_persons) > 10 else "")
    )

    try:
        _send_realtime_notifications(new_persons, punch_date, cfg)
    except Exception as e:  # noqa: BLE001
        _log(f"通知发送异常: {e}\n{traceback.format_exc()}")

    # 飞书多维表格同步：每发现一个未参保人员，异步推一条到飞书 webhook
    # 由 feishu_webhook_pusher worker 异步处理（不阻塞主流程；失败落 DLQ 不影响下游）
    try:
        feishu_pushed = 0
        for p in new_persons:
            record = dict(p)  # 复制避免外部修改
            record["punch_date"] = punch_date
            record["source"] = "realtime"
            if push_uninsured_person(record, source="realtime"):
                feishu_pushed += 1
        if feishu_pushed:
            _log(f"飞书多维表格异步推送 {feishu_pushed} 条（worker 后台处理）")
    except Exception as e:  # noqa: BLE001
        _log(f"飞书 webhook 入队异常（不影响主流程）: {e}")

    notified.update(p["id_number"] for p in new_persons)
    cfg["realtime_notified_today"] = {
        "punch_date": punch_date,
        "ids": list(notified),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        save_config(cfg)
    except Exception as e:  # noqa: BLE001
        _log(f"保存 realtime_notified_today 失败（不影响本次发送）: {e}")


def _worker_loop():
    _log("实时消费者工作线程启动")
    try:
        _refresh_manager_cache()
    except Exception:
        pass
    last_refresh = time.time()
    batch_window = 3
    max_batch = 200
    try:
        cfg0 = load_config()
        batch_window = int((cfg0.get("realtime") or {}).get("batch_window_seconds", 3))
        max_batch = int((cfg0.get("realtime") or {}).get("max_batch", 200))
    except Exception:
        pass

    while not _STOP.is_set():
        try:
            # 阻塞等待首个事件（不超过窗口），实现秒级实时
            item = _QUEUE.get(timeout=batch_window)
            batch = [item]
            # 窗口内尽量多捞，但不超过上限
            while len(batch) < max_batch:
                try:
                    batch.append(_QUEUE.get_nowait())
                except queue.Empty:
                    break
        except queue.Empty:
            continue

        _STATS["batches"] += 1
        _STATS["last_batch_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if time.time() - last_refresh > MANAGER_REFRESH_SEC:
            try:
                _refresh_manager_cache()
            except Exception:
                pass
            last_refresh = time.time()
        try:
            _process_events(batch)
        except Exception as e:  # noqa: BLE001
            _STATS["errors"] += 1
            _log(f"批处理异常: {e}\n{traceback.format_exc()}")
    _log("实时消费者工作线程退出")


# ============ 对外接口 ============

def start_realtime_consumer(session_manager=None):
    """启动实时消费者（幂等，重复调用不会起多个线程）。"""
    global _STARTED, _WORKER, _SESSION_MANAGER
    if _STARTED:
        _log("消费者已在运行，忽略重复启动")
        return
    _SESSION_MANAGER = session_manager
    _STOP.clear()
    _WORKER = threading.Thread(target=_worker_loop, name="realtime-consumer", daemon=True)
    _WORKER.start()
    _STARTED = True
    _STATS["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log("实时消费者已启动")


def stop_realtime_consumer():
    global _STARTED
    _STOP.set()
    _STARTED = False
    _log("已请求停止实时消费者")


def submit_punch_events(events) -> int:
    """提交一批打卡事件（来自 ERP 推送 / MQ 桥接 / 测试）。返回接受条数。"""
    if isinstance(events, dict):
        events = [events]
    if not isinstance(events, (list, tuple)):
        return 0
    n = 0
    for e in events:
        if isinstance(e, dict):
            _QUEUE.put(e)
            n += 1
    _STATS["accepted"] += n
    return n


def get_status() -> dict:
    with _MANAGER_LOCK:
        cache_size = len(_MANAGER_CACHE)
    return {
        "started": _STARTED,
        "queue_size": _QUEUE.qsize(),
        "accepted_total": _STATS["accepted"],
        "batches_total": _STATS["batches"],
        "last_batch_at": _STATS["last_batch_at"],
        "last_processed": _STATS["last_processed"],
        "errors": _STATS["errors"],
        "manager_cache_size": cache_size,
        "started_at": _STATS["started_at"],
    }
