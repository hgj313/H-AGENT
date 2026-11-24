# -*- coding: utf-8 -*-
"""
MQ -> HTTP 打卡事件桥接程序 (保险管理AI助手)

作用
----
ERP 系统每产生一条打卡记录，通过现有 MQ 消息队列异步推送。
本程序作为「轻量桥接」订阅 ERP 的 MQ 主题，把打卡事件规范化后，
批量转发到智能体的 HTTP 入口 `POST /api/punch/events`，
由智能体侧的实时消费者 (realtime_punch_consumer) 完成：
  - 入库到 punch_records
  - 一次性核对该批人员是否有正常保险
  - 无保单者 -> 短信+邮件至项目经理（测试模式路由到测试联系人）
  - 汇总邮件 -> 保险管理人员

支持的后端 (backend)
--------------------
  - rabbitmq : 通过 pika 订阅（推荐，企业常用）
  - rocketmq : 通过阿里云 mq_http_sdk（HTTP 协议）订阅（国产 JAVA-ERP 常用，已适配 ONS 互联网 HTTP 接入点 :80）
  - kafka    : 通过 kafka-python 订阅（高吞吐场景）
  - mock     : 不连真实 broker，直接用内存队列发布样例事件，
               用于本地验证「转发逻辑」是否打通（无需 MQ 环境）

设计要点（应对「多项目同时打卡」）
--------------------------------
  - 每条 MQ 消息独立转发，由下游 3s 滑动窗口批处理合并，
    把 N 次「入库+查保险+发通知」压成少数几次，性能稳定。
  - 整批只查一次有效保单快照，O(批大小)。
  - 断线自动重连（指数退避），转发失败带重试 + 本地死信队列 (DLQ)。

依赖：仅 `requests` 为必需；pika/rocketmq/kafka 按所选 backend 懒加载。
"""

import json
import logging
import os
import signal
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("mq_punch_bridge")

# 同步写一份到 mq_bridge_stderr.log（按大小自动轮转，避免无限增长）
#  - 单个文件 10MB 切分一次
#  - 保留 5 个备份（.log.1 ~ .log.5）
#  - 总占用上限 = 6 × 10MB = 60MB
_log_path = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "mq_bridge_stderr.log",
))
try:
    _fh = RotatingFileHandler(
        _log_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,              # 保留 .log.1 ~ .log.5 共 5 个备份
        encoding="utf-8",
    )
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_fh)
except Exception as _e:
    # 文件日志加不上不影响运行（stderr 仍在屏幕）
    print(f"[warn] cannot attach rotating file handler: {_e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 单实例锁：防止多个 bridge 进程同时跑（互相抢消费权导致数据丢失）
# ---------------------------------------------------------------------------
_BRIDGE_LOCK_PORT = 8767  # 锁端口，独立于 8765 业务端口

# 全局停用标记（2026-11-24：打卡数据改由 erp_feishu_direct 直连飞书多维表格）
# 存在则本桥接不启动 —— 消费组让给直连消费者，避免同组互相抢消息。
DISABLE_FLAG = r"C:\insurance-automation\.assistant_disabled"


def _acquire_single_instance_lock():
    """获取单实例锁（绑定 127.0.0.1:8767）。
    返回 socket 对象保持引用；返回 None 表示锁已被占用（有另一个实例在跑）。"""
    import socket as _socket
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 0)
    try:
        sock.bind(("127.0.0.1", _BRIDGE_LOCK_PORT))
        sock.listen(1)
        return sock
    except OSError:
        try:
            sock.close()
        except Exception:
            pass
        return None

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "mq_bridge_config.json",
)

# 智能体事件入口（与 server.py 的 /api/punch/events 对齐）
DEFAULT_ENDPOINT = "http://localhost:8765/api/punch/events"


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------
def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """加载桥接配置；允许环境变量覆盖关键项。"""
    cfg: Dict[str, Any] = {
        "mq": {
            "backend": "mock",          # rabbitmq | rocketmq | kafka | mock
            "host": "localhost",
            "port": 5672,
            "username": "",
            "password": "",
            "virtual_host": "/",
            "topic": "erp.punch.events",   # 主题/队列名/路由键（按后端语义）
            "tag": "",                      # RocketMQ 消息标签，精确订阅过滤（如 CLOCK_RECORD_CREATE）
            "exchange": "",                 # rabbitmq 可选
            "group": "insurance-agent",     # kafka consumer group / rocketmq consumer group
            "broker": "",                   # kafka bootstrap_servers / 其他
            "ca_cert": "",
            "use_tls": False,
        },
        "forward": {
            "endpoint": DEFAULT_ENDPOINT,
            "token": "",                     # 可选 Bearer 鉴权
            "timeout": 15,
            "retry": 3,
            "retry_backoff": 2.0,            # 指数退避基数(秒)
        },
        # ERP 字段 -> 智能体字段 的重命名映射（可选）。
        # 智能体端点已兼容驼峰/蛇形，这里仅补充 ERP 特殊命名。
        "rename": {
            # 例: "employeeName": "memberName", "idCard": "identificationNumber",
            #      "project": "projectName", "team": "teamName"
        },
        "source_tag": "mq",                  # 写入事件的 source 字段
    }
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            _deep_update(cfg, user)
            logger.info("已加载配置: %s", path)
        except Exception as e:
            logger.warning("配置加载失败，使用默认: %s", e)
    # 1) 加载项目根目录 .env（若存在），注入密钥等环境变量（不覆盖 OS 已有值）
    _load_dotenv(os.path.join(os.path.dirname(path), ".env"))

    # 2) 环境变量覆盖（服务器部署优先使用环境变量；密钥禁止写入配置文件明文）
    mq = cfg["mq"]
    fwd = cfg["forward"]
    if os.environ.get("BRIDGE_ENDPOINT"):
        fwd["endpoint"] = os.environ["BRIDGE_ENDPOINT"]
    if os.environ.get("BRIDGE_TOKEN"):
        fwd["token"] = os.environ["BRIDGE_TOKEN"]
    if os.environ.get("BRIDGE_MQ_BACKEND"):
        mq["backend"] = os.environ["BRIDGE_MQ_BACKEND"]
    # RocketMQ 密钥（必填）：ROCKETMQ_* 优先，MQ_* 为兼容别名
    if os.environ.get("ROCKETMQ_ACCESS_KEY"):
        mq["access_key"] = os.environ["ROCKETMQ_ACCESS_KEY"]
    if os.environ.get("ROCKETMQ_SECRET_KEY"):
        mq["secret_key"] = os.environ["ROCKETMQ_SECRET_KEY"]
    if os.environ.get("MQ_ACCESS_KEY"):
        mq["access_key"] = os.environ["MQ_ACCESS_KEY"]
    if os.environ.get("MQ_SECRET_KEY"):
        mq["secret_key"] = os.environ["MQ_SECRET_KEY"]
    # 部署时可覆盖的连接参数
    if os.environ.get("MQ_HOST"):
        mq["host"] = os.environ["MQ_HOST"]
    if os.environ.get("MQ_PORT"):
        mq["port"] = int(os.environ["MQ_PORT"])
    if os.environ.get("MQ_INSTANCE_ID"):
        mq["instance_id"] = os.environ["MQ_INSTANCE_ID"]
    if os.environ.get("MQ_TOPIC"):
        mq["topic"] = os.environ["MQ_TOPIC"]
    if os.environ.get("MQ_TAG"):
        mq["tag"] = os.environ["MQ_TAG"]
    if os.environ.get("MQ_GROUP"):
        mq["group"] = os.environ["MQ_GROUP"]
    if os.environ.get("MQ_PROTOCOL"):
        mq["protocol"] = os.environ["MQ_PROTOCOL"]
    return cfg


def _deep_update(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def _load_dotenv(path: str) -> None:
    """极简 .env 解析：仅填充尚未存在的环境变量（不覆盖 OS 已有值）。

    用于本地/服务器部署时注入密钥等敏感配置，避免明文写入 JSON 配置。
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        logger.info("已加载 .env: %s", path)
    except Exception as e:  # noqa: BLE001
        logger.warning(".env 加载失败: %s", e)


# ---------------------------------------------------------------------------
# 事件规范化
# ---------------------------------------------------------------------------
def extract_events(raw: Any, rename: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    从一条 MQ 消息体解析出事件列表。
    ERP 可能发送：
      - 数组 [...]
      - {"events": [...]}  /  {"data": [...]}  /  {"records": [...]}
      - 单条对象 {...}
    返回统一为列表。
    """
    if raw is None:
        return []
    # 字符串先尝试 JSON 解析
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return []
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        # 循环解析（处理双层 JSON 字符串：Java/Kotlin 序列化时会把整个 JSON
        # 再用引号包一层，比如 "{\"a\":1}"；json.loads 后仍是字符串）。
        # 最多解析 3 层，避免异常消息死循环
        for _ in range(3):
            try:
                raw = json.loads(s)
            except Exception:
                # 非 JSON：可能是逗号分隔或纯文本，无法解析
                logger.warning("MQ 消息非 JSON，已忽略: %s", s[:120])
                return []
            if not isinstance(raw, str):
                break
            s = raw.strip()
            if not s:
                return []

    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        for key in ("events", "data", "records", "items", "list"):
            if isinstance(raw.get(key), list):
                items = raw[key]
                break
        else:
            items = [raw]  # 单条对象
    else:
        return []

    events = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ev = {}
        for k, v in it.items():
            nk = rename.get(k, k)
            ev[nk] = v
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# HTTP 转发（带重试 + DLQ）
# ---------------------------------------------------------------------------
DLQ_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "mq_bridge_dlq.jsonl",
)


def forward_events(events: List[Dict[str, Any]], cfg: Dict[str, Any],
                   source: str = "mq") -> bool:
    """把一批事件 POST 到智能体入口，失败重试。返回是否成功。"""
    if not events:
        return True
    fwd = cfg.get("forward", {})
    endpoint = fwd.get("endpoint", DEFAULT_ENDPOINT)
    token = fwd.get("token", "")
    timeout = int(fwd.get("timeout", 15))
    max_retry = int(fwd.get("retry", 3))
    backoff = float(fwd.get("retry_backoff", 2.0))

    payload = {"events": events, "source": source}
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    import requests  # 必需依赖，懒加载于真正转发时

    last_err = None
    for attempt in range(1, max_retry + 1):
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                logger.info("转发成功: %d 条事件 -> %s (HTTP 200)", len(events), endpoint)
                return True
            # 业务层明确失败（如 readonly_db）也视为需 DLQ，不再无谓重试
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.warning("转发返回非 200 (第%d次): %s", attempt, last_err)
        except Exception as e:
            last_err = repr(e)
            logger.warning("转发异常 (第%d次): %s", attempt, last_err)
        if attempt < max_retry:
            time.sleep(backoff * (2 ** (attempt - 1)))
    # 全部失败 -> 写入死信队列
    _write_dlq(events, cfg, source, last_err)
    return False


def _write_dlq(events: List[Dict[str, Any]], cfg: Dict[str, Any],
               source: str, err: str) -> None:
    try:
        with open(DLQ_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source": source,
                "error": err,
                "events": events,
            }, ensure_ascii=False) + "\n")
        logger.error("已写入死信队列: %s (%d 条)", DLQ_PATH, len(events))
    except Exception as e:
        logger.error("死信写入失败: %s", e)


def _handle_message(raw: Any, cfg: Dict[str, Any]) -> None:
    rename = cfg.get("rename", {}) or {}

    # 详细消费日志（排查字段兼容性问题）
    raw_preview = raw if isinstance(raw, str) else (
        raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else repr(raw)
    )
    logger.info("=" * 60)
    logger.info("[消费详情] 原始消息体 (前 500 字): %s",
                raw_preview[:500] + ("..." if len(raw_preview) > 500 else ""))

    events = extract_events(raw, rename)
    logger.info("[消费详情] 解析后事件数: %d", len(events))

    if not events:
        logger.warning("[消费详情] 解析后事件为空，跳过转发")
        return

    # 打印每个事件的关键字段
    for i, ev in enumerate(events):
        idn = ev.get("identificationNumber") or ev.get("id_number") or "(空)"
        nm = ev.get("memberName") or ev.get("name") or "(空)"
        proj = ev.get("projectName") or ev.get("project_name") or "(空)"
        eid = ev.get("id") or ev.get("erp_id") or "(空)"
        # 业务字段（劳务/班组/工种/审核/电话）：方便核对未参保人归属的劳务公司
        supplier = ev.get("supplierName") or ev.get("supplier_name") or "(空)"
        team = ev.get("teamName") or ev.get("team_name") or "(空)"
        category = ev.get("categoryName") or ev.get("category_name") or "(空)"
        exam = ev.get("examinationStatusName") or ev.get("examination_status_name") or "(空)"
        tel = ev.get("telephone") or ev.get("phone") or "(空)"
        # 项目经理三件套：ERP 实时消息体常带，方便核对通知是否走通
        mgr_name = (ev.get("projectManager") or ev.get("project_manager")
                    or ev.get("projectManagerName") or "(空)")
        mgr_phone = (ev.get("managerPhone") or ev.get("manager_phone")
                     or ev.get("projectManagerPhone") or "(空)")
        mgr_email = (ev.get("managerEmail") or ev.get("manager_email")
                     or ev.get("projectManagerEmail") or "(空)")
        # 截断长字符串，避免一行被刷屏
        def _t(v, n=40):
            return v[:n] + "…" if isinstance(v, str) and len(v) > n else v
        logger.info(
            "[消费详情] 事件 #%d | id=%s | name=%s | id_number=%s | "
            "project=%s | supplier=%s | team=%s | category=%s | "
            "exam=%s | tel=%s | mgr_name=%s | mgr_phone=%s | mgr_email=%s | "
            "keys=%s",
            i + 1, eid, nm, idn,
            _t(proj, 50), _t(supplier, 40), _t(team, 20), _t(category, 20),
            exam, tel, mgr_name, mgr_phone, mgr_email,
            list(ev.keys()),
        )

    forward_events(events, cfg, source=cfg.get("source_tag", "mq"))


# ---------------------------------------------------------------------------
# Mock 后端（本地验证转发逻辑，无需真实 MQ）
# ---------------------------------------------------------------------------
def run_mock(cfg: Dict[str, Any]) -> None:
    """模拟 ERP 连续推送若干打卡事件，验证转发链路。"""
    logger.info("=== MOCK 模式：不连接真实 MQ，直接验证转发逻辑 ===")
    samples = [
        {"id": "MQ-1001", "memberName": "雷天林",
         "identificationNumber": "510228196402241013",
         "projectName": "广州华润白鹅潭项目二区核心南区景观工程",
         "teamName": "一班", "supplierName": "某劳务", "categoryName": "普工"},
        {"id": "MQ-1002", "memberName": "陈昌文",
         "identificationNumber": "513031196603132972",
         "projectName": "成都万华麓湖生态城C19组团景观总承包工程",
         "teamName": "一班", "supplierName": "某劳务", "categoryName": "普工"},
        # 模拟「多项目同时打卡」：批量消息
        {"events": [
            {"id": "MQ-2001", "memberName": "王五",
             "identificationNumber": "500228197001011234",
             "projectName": "重庆某项目景观工程", "categoryName": "普工"},
            {"id": "MQ-2002", "memberName": "赵六",
             "identificationNumber": "500228198002022345",
             "projectName": "重庆某项目景观工程", "categoryName": "普工"},
        ]},
    ]
    for i, msg in enumerate(samples, 1):
        logger.info("模拟 ERP 推送 #%d", i)
        _handle_message(msg, cfg)
        time.sleep(0.5)
    logger.info("=== MOCK 推送完成，请查看 realtime.log 确认处理 ===")


# ---------------------------------------------------------------------------
# RabbitMQ 后端
# ---------------------------------------------------------------------------
def run_rabbitmq(cfg: Dict[str, Any]) -> None:
    import pika  # 懒加载

    mq = cfg["mq"]
    creds = pika.PlainCredentials(mq.get("username") or "guest",
                                  mq.get("password") or "guest")
    params = pika.ConnectionParameters(
        host=mq.get("host", "localhost"),
        port=int(mq.get("port", 5672)),
        virtual_host=mq.get("virtual_host", "/"),
        credentials=creds,
        heartbeat=30,
    )
    topic = mq.get("topic", "erp.punch.events")
    exchange = mq.get("exchange") or ""

    def on_message(ch, method, properties, body):
        try:
            _handle_message(body, cfg)
        except Exception:
            logger.exception("处理 MQ 消息异常")
        finally:
            try:
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception:
                pass

    while not _stop.is_set():
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue=topic, durable=True)
            if exchange:
                ch.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
                ch.queue_bind(queue=topic, exchange=exchange, routing_key=topic)
            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue=topic, on_message_callback=on_message)
            logger.info("RabbitMQ 已连接，订阅队列: %s", topic)
            ch.start_consuming()
        except Exception as e:
            logger.warning("RabbitMQ 连接中断，5s 后重连: %s", e)
            time.sleep(5)


# ---------------------------------------------------------------------------
# RocketMQ 后端
# ---------------------------------------------------------------------------
def _patch_mq_http_sdk_compat() -> None:
    """兼容补丁：mq_http_sdk 为旧版 Python 编写，给 HTTPSConnection 传了
    Python 3.12+ 已移除的 `strict` 参数（MQHTTPSConnection.__init__ 用关键字
    `strict=` 传递 -> TypeError: unexpected keyword argument 'strict'）。
    同时原版 MQHTTPSConnection.__init__ 未设置 connection_timeout，connect() 会
    AttributeError。这里替换两个连接类的 __init__，去掉 strict 并补上
    connection_timeout 默认值，使 SDK 在 Python 3.12+ 上可正常跑 HTTPS。

    补丁写在本项目内（不修改 site-packages），venv 重建后只要跑本脚本即生效。
    """
    try:
        from mq_http_sdk import mq_http as _m
    except Exception:
        return
    import http.client as _hc

    def _http_init(self, host, port=None, strict=None, connection_timeout=60):
        _hc.HTTPConnection.__init__(self, host, port)
        self.request_length = 0
        self.connection_timeout = connection_timeout

    def _https_init(self, host, port=None, strict=None, connection_timeout=60):
        _hc.HTTPSConnection.__init__(self, host, port)
        self.request_length = 0
        self.connection_timeout = connection_timeout

    _m.MQHTTPConnection.__init__ = _http_init
    _m.MQHTTPSConnection.__init__ = _https_init


def run_rocketmq(cfg: Dict[str, Any]) -> None:
    """Aliyun RocketMQ **HTTP 协议**消费者（mq_http_sdk）。

    重要：当前接入点 (...:80 / http://) 是 RocketMQ 的 HTTP 协议接入点，
    不能用 TCP 版 rocketmq-client-python（namesrv）连接，必须用 HTTP SDK。
    本消费者只做「订阅 + 读取」消息，属只读操作，
    不向 ERP / MQ 写入或修改任何数据（符合只读约束）。
    """
    from mq_http_sdk.mq_client import MQClient
    from mq_http_sdk.mq_consumer import MQConsumer  # noqa: F401 (保持 import 一致性)
    from mq_http_sdk.mq_exception import MQExceptionBase
    _patch_mq_http_sdk_compat()  # Python 3.12+ 兼容：去掉 HTTPSConnection 的 strict 参数

    mq = cfg["mq"]
    host = mq.get("host", "")
    port = mq.get("port")
    scheme = "https" if mq.get("use_tls") else "http"
    if not host.startswith("http"):
        host = f"{scheme}://{host}" + (f":{port}" if port else "")
    access_key = mq.get("access_key") or ""
    secret_key = mq.get("secret_key") or ""
    instance_id = mq.get("instance_id") or ""
    topic = mq.get("topic", "")
    tag = mq.get("tag", "") or ""      # 精确订阅：仅拉取该 tag 的消息（如 CLOCK_RECORD_CREATE）
    group = mq.get("group", "")

    if not (access_key and secret_key):
        logger.error(
            "RocketMQ 缺少 access_key/secret_key，无法连接。"
            "请通过环境变量 ROCKETMQ_ACCESS_KEY / ROCKETMQ_SECRET_KEY 注入"
            "（或 MQ_ACCESS_KEY / MQ_SECRET_KEY），不要写入配置文件明文。"
        )
        return
    if not (host and topic and group):
        logger.error("RocketMQ 配置不完整：需要 host/topic/group")
        return

    client = MQClient(host, access_key, secret_key)
    consumer = client.get_consumer(instance_id, topic, group, tag)
    logger.info(
        "RocketMQ(HTTP) 已订阅: topic=%s tag=%s group=%s instance=%s host=%s",
        topic, tag or "(全部)", group, instance_id, host,
    )

    wait_seconds = 3   # 长轮询挂起时长（最多 30s）
    batch = 3          # 单次最多拉取条数（最多 16）
    # 连续失败上限：达到后停止桥接进程，避免被网络拦截时无限重试刷屏
    max_consecutive_errors = int(mq.get("max_consecutive_errors", 5))
    consecutive_errors = 0
    last_heartbeat = time.time()
    heartbeat_interval = 300  # 每 5 分钟打一次心跳，便于排查「bridge 是否还活着」
    total_received = 0
    total_forwarded = 0
    total_failed = 0
    while not _stop.is_set():
        # 心跳日志（每 5 分钟即使没消息也打，便于排查「bridge 是否活着」）
        if time.time() - last_heartbeat >= heartbeat_interval:
            logger.info(
                "[心跳] bridge 存活 | 累计收到 %d / 转发 %d / 失败 %d",
                total_received, total_forwarded, total_failed,
            )
            last_heartbeat = time.time()

        try:
            recv_msgs = consumer.consume_message(batch, wait_seconds)
            consecutive_errors = 0  # 正常返回即清零
            if recv_msgs:
                total_received += len(recv_msgs)
                logger.info("收到 MQ 消息 %d 条（累计收到 %d）", len(recv_msgs), total_received)
        except MQExceptionBase as e:
            if getattr(e, "type", "") == "MessageNotExist":
                consecutive_errors = 0
                continue
            consecutive_errors += 1
            logger.warning(
                "RocketMQ 消费异常(%d/%d)，2s 后重试: %s",
                consecutive_errors, max_consecutive_errors, e,
            )
            if consecutive_errors >= max_consecutive_errors:
                logger.error(
                    "RocketMQ 连续失败 %d 次，疑似被网络拦截或服务不可用，停止桥接进程。",
                    consecutive_errors,
                )
                return
            time.sleep(2)
            continue
        except Exception as e:  # 连接/网络层异常
            consecutive_errors += 1
            logger.warning(
                "RocketMQ 连接异常(%d/%d)，5s 后重试: %s",
                consecutive_errors, max_consecutive_errors, e,
            )
            if consecutive_errors >= max_consecutive_errors:
                logger.error(
                    "RocketMQ 连续失败 %d 次，疑似被网络拦截或服务不可用，停止桥接进程。",
                    consecutive_errors,
                )
                return
            time.sleep(5)
            continue

        for msg in recv_msgs:
            try:
                _handle_message(msg.message_body, cfg)
                total_forwarded += 1
            except Exception:
                total_failed += 1
                logger.exception("处理 RocketMQ 消息异常")
            try:
                consumer.ack_message([msg.receipt_handle])
            except Exception:
                logger.warning("RocketMQ ack 失败(可能已超时): %s", msg.receipt_handle)


# ---------------------------------------------------------------------------
# Kafka 后端
# ---------------------------------------------------------------------------
def run_kafka(cfg: Dict[str, Any]) -> None:
    from kafka import KafkaConsumer  # 懒加载

    mq = cfg["mq"]
    topic = mq.get("topic", "erp.punch.events")
    brokers = mq.get("broker") or f"{mq.get('host','localhost')}:{int(mq.get('port',9092))}"
    group = mq.get("group", "insurance-agent")

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=brokers.split(","),
        group_id=group,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda v: v,  # 保留原始 bytes，交给 extract_events
    )
    logger.info("Kafka 已订阅: %s @ %s", topic, brokers)
    for msg in consumer:
        if _stop.is_set():
            break
        try:
            _handle_message(msg.value, cfg)
        except Exception:
            logger.exception("处理 Kafka 消息异常")


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
_stop = threading.Event()


def _install_signal_handlers() -> None:
    def _h(signum, frame):
        logger.info("收到退出信号，停止桥接...")
        _stop.set()
    try:
        signal.signal(signal.SIGINT, _h)
        signal.signal(signal.SIGTERM, _h)
    except Exception:
        pass


def main() -> None:
    # 全局停用标记：存在则不启动（消费组让给 erp_feishu_direct 直连消费者）
    if os.path.exists(DISABLE_FLAG):
        logger.info("检测到停用标记 %s，MQ 桥接已停用，消费组让给直连消费者。", DISABLE_FLAG)
        sys.exit(0)

    cfg = load_config()
    backend = cfg["mq"].get("backend", "mock")

    # 单实例锁：防止多个 bridge 同时跑（互相抢消费权）
    _lock_sock = _acquire_single_instance_lock()
    if _lock_sock is None:
        logger.error(
            "另一个 bridge 实例已在运行（端口 %d 被占用）。本实例退出，避免多实例抢消费权。",
            _BRIDGE_LOCK_PORT,
        )
        sys.exit(2)
    # 保持 _lock_sock 引用（不关闭），进程结束自动释放

    logger.info("启动 MQ->HTTP 桥接 | backend=%s | endpoint=%s",
                backend, cfg["forward"].get("endpoint"))
    _install_signal_handlers()

    runners = {
        "mock": run_mock,
        "rabbitmq": run_rabbitmq,
        "rocketmq": run_rocketmq,
        "kafka": run_kafka,
    }
    runner = runners.get(backend)
    if not runner:
        logger.error("未知 backend: %s", backend)
        sys.exit(2)
    try:
        runner(cfg)
    except KeyboardInterrupt:
        _stop.set()
    except Exception:
        logger.exception("桥接程序异常退出")
        sys.exit(1)
    logger.info("桥接程序已停止")


if __name__ == "__main__":
    main()
