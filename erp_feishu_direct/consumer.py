"""ERP MQ → 飞书多维表格 直连消费者（独立进程）

运行方式::

    python -m erp_feishu_direct.consumer

数据流::

    ERP 打卡 → RocketMQ(JS_PROD_MQ / CLOCK_RECORD_CREATE)
                    ↓ 独立消费组 feishu-direct-sync
              本进程攒批（滑动窗口）
                    ↓
              飞书多维表格

与主项目的关系：**完全独立**。
- 不依赖 8765 服务（本进程不 import web_app）
- 不写本地 SQLite（内存直传 + 轻量 JSON 幂等映射）
- 与现有 MQ 桥接使用**不同的消费组**，两条链路互不抢消息

攒批策略
--------
ERP 打卡是逐条推送的，若每条都调一次飞书 API，10 QPS 的限制会立刻打满。
本进程用一个滑动窗口把多条消息合并成一批（默认 3 秒或满 500 条触发），
再一次性批量写入飞书（单次 ≤500 条）。
"""

import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List

from insurance_agent.infrastructure.feishu_bitable_client import (
    FeishuBitableClient,
    load_client_from_config,
)

from erp_feishu_direct.config import (
    LOCK_PORT,
    SYNC_MAP_PATH,
    load_config,
    missing_keys,
)
from erp_feishu_direct.mapper import normalize_events
from erp_feishu_direct.store import SyncMapStore
from erp_feishu_direct.writer import FeishuWriter

logger = logging.getLogger("erp_feishu_direct")

_STOP = threading.Event()
_STATS = {
    "started_at": None,
    "received": 0,
    "written": 0,
    "created": 0,
    "updated": 0,
    "failed": 0,
    "last_error": None,
}


def _setup_logging() -> None:
    """日志：控制台 + 轮转文件（避免无限增长）"""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "erp_feishu_direct.log",
    )
    try:
        fh = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 无法创建日志文件: {e}", file=sys.stderr)


def _acquire_single_instance_lock():
    """单实例锁：绑定 127.0.0.1:8768，防止多实例抢消费权导致重复消费"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind(("127.0.0.1", LOCK_PORT))
        sock.listen(1)
        return sock
    except OSError:
        try:
            sock.close()
        except Exception:
            pass
        return None


def _install_signal_handlers() -> None:
    def _h(signum, frame):
        logger.info("收到退出信号 %s，停止直连消费...", signum)
        _STOP.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _h)
        except Exception:
            pass


def _patch_mq_http_sdk_compat() -> None:
    """兼容补丁：mq_http_sdk 给 HTTPSConnection 传了 Python 3.12+ 已移除的 `strict` 参数，
    且未设置 connection_timeout。原样放在本模块内，保证独立进程不依赖主项目的补丁。
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


def _build_writer(cfg: Dict[str, Any]) -> FeishuWriter:
    """构造写入器（飞书客户端 + 幂等映射存储）"""
    fs = cfg["feishu"]
    client = load_client_from_config(fs)
    store = SyncMapStore(
        SYNC_MAP_PATH,
        keep_days=int(cfg.get("sync", {}).get("map_keep_days", 7)),
    )
    return FeishuWriter(
        client=client,
        store=store,
        field_mapping=None,
        table_id=fs.get("table_id", ""),
        max_batch_size=int(cfg.get("batch", {}).get("max_batch_size", 500)),
        retry=int(cfg.get("sync", {}).get("retry", 3)),
        retry_backoff=float(cfg.get("sync", {}).get("retry_backoff", 2.0)),
    )


def _flush(writer: FeishuWriter, pending: List[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
    """把攒下的一批事件写入飞书"""
    if not pending:
        return
    batch_cfg = cfg.get("batch", {})
    window = float(batch_cfg.get("window_seconds", 3))
    result = writer.write_batch(pending)

    _STATS["written"] += result["created"] + result["updated"]
    _STATS["created"] += result["created"]
    _STATS["updated"] += result["updated"]
    _STATS["failed"] += result["failed"]

    logger.info(
        "[写入飞书] 本批 %d 条 → 新增 %d / 更新 %d / 跳过 %d / 失败 %d（攒批窗口 %.1fs）",
        len(pending), result["created"], result["updated"],
        result["skipped"], result["failed"], window,
    )
    pending.clear()


def run(cfg: Dict[str, Any]) -> int:
    """主循环：订阅 MQ → 攒批 → 写飞书

    Returns:
        进程退出码（0 正常，1 配置缺失）
    """
    missing = missing_keys(cfg)
    if missing:
        logger.error("缺少必要凭证: %s", ", ".join(missing))
        logger.error("请在 .env 中配置这些环境变量后重试。")
        return 1

    mq = cfg["mq"]
    batch_cfg = cfg.get("batch", {})
    window = float(batch_cfg.get("window_seconds", 3))
    max_batch = int(batch_cfg.get("max_batch_size", 500))
    consume_batch = int(batch_cfg.get("consume_batch", 16))
    wait_seconds = int(batch_cfg.get("wait_seconds", 3))

    from mq_http_sdk.mq_client import MQClient
    from mq_http_sdk.mq_exception import MQExceptionBase

    _patch_mq_http_sdk_compat()

    host = mq.get("host", "")
    if not host.startswith("http"):
        scheme = "https" if mq.get("use_tls") else "http"
        host = f"{scheme}://{host}" + (f":{mq['port']}" if mq.get("port") else "")

    client = MQClient(host, mq["access_key"], mq["secret_key"])
    consumer = client.get_consumer(
        mq.get("instance_id", ""), mq["topic"], mq["group"], mq.get("tag", "")
    )

    logger.info("=" * 60)
    logger.info("ERP → 飞书多维表格 直连消费者")
    logger.info("  MQ: topic=%s tag=%s group=%s", mq["topic"], mq.get("tag") or "(全部)", mq["group"])
    logger.info("  飞书: app_token=%s table=%s", cfg["feishu"].get("app_token", ""),
                cfg["feishu"].get("table_id") or cfg["feishu"].get("table_name") or "(自动查找)")
    logger.info("  攒批: 窗口 %ds / 单批上限 %d", window, max_batch)
    logger.info("=" * 60)

    writer = _build_writer(cfg)
    rename = cfg.get("rename", {}) or {}

    pending: List[Dict[str, Any]] = []
    last_flush = time.time()
    consecutive_errors = 0
    max_consecutive_errors = int(mq.get("max_consecutive_errors", 5))
    last_heartbeat = time.time()
    heartbeat_interval = 300

    _STATS["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    while not _STOP.is_set():
        # 心跳：即使没消息也每 5 分钟打一次，便于确认进程存活
        if time.time() - last_heartbeat >= heartbeat_interval:
            logger.info(
                "[心跳] 存活 | 累计收到 %d / 写入 %d（新增 %d / 更新 %d）/ 失败 %d",
                _STATS["received"], _STATS["written"],
                _STATS["created"], _STATS["updated"], _STATS["failed"],
            )
            last_heartbeat = time.time()

        try:
            recv_msgs = consumer.consume_message(consume_batch, wait_seconds)
            consecutive_errors = 0
            if recv_msgs:
                _STATS["received"] += len(recv_msgs)
                logger.info("收到 MQ 消息 %d 条（累计 %d）", len(recv_msgs), _STATS["received"])
        except MQExceptionBase as e:
            if getattr(e, "type", "") == "MessageNotExist":
                consecutive_errors = 0
                # 长轮询超时也要检查是否该刷批
                if pending and time.time() - last_flush >= window:
                    _flush(writer, pending, cfg)
                    last_flush = time.time()
                continue
            consecutive_errors += 1
            _STATS["last_error"] = str(e)
            logger.warning("MQ 消费异常(%d/%d)，2s 后重试: %s",
                           consecutive_errors, max_consecutive_errors, e)
            if consecutive_errors >= max_consecutive_errors:
                logger.error("MQ 连续失败 %d 次，停止进程。", consecutive_errors)
                return 1
            time.sleep(2)
            continue
        except Exception as e:  # noqa: BLE001
            consecutive_errors += 1
            _STATS["last_error"] = repr(e)
            logger.warning("MQ 连接异常(%d/%d)，5s 后重试: %s",
                           consecutive_errors, max_consecutive_errors, e)
            if consecutive_errors >= max_consecutive_errors:
                logger.error("MQ 连续失败 %d 次，停止进程。", consecutive_errors)
                return 1
            time.sleep(5)
            continue

        # 处理消息 → 解析事件 → 放进待写队列
        for msg in recv_msgs:
            try:
                events = normalize_events(msg.message_body, rename)
                for ev in events:
                    pending.append(ev)
                    # 攒够一批立即刷
                    if len(pending) >= max_batch:
                        _flush(writer, pending, cfg)
                        last_flush = time.time()
            except Exception:
                logger.exception("解析 MQ 消息异常")

            # 攒批窗口到期也刷
            if pending and time.time() - last_flush >= window:
                _flush(writer, pending, cfg)
                last_flush = time.time()

            # ⚠️ ack 时机：写入飞书成功后才 ack。
            #    这里先 ack（MQ 语义是「已消费」），DLQ 由写入器负责兜底，
            #    避免因飞书短暂故障导致 MQ 消息堆积到重试上限。
            try:
                consumer.ack_message([msg.receipt_handle])
            except Exception:
                logger.warning("MQ ack 失败(可能已超时): %s", msg.receipt_handle)

    # 退出前把剩余批次刷完
    if pending:
        logger.info("退出前刷出剩余 %d 条", len(pending))
        _flush(writer, pending, cfg)

    logger.info("直连消费者已停止 | 统计: %s", _STATS)
    return 0


def main() -> None:
    _setup_logging()
    _install_signal_handlers()

    lock_sock = _acquire_single_instance_lock()
    if lock_sock is None:
        logger.error(
            "另一个直连实例已在运行（端口 %d 被占用）。本实例退出，避免重复消费。",
            LOCK_PORT,
        )
        return

    cfg = load_config()
    if not cfg.get("sync", {}).get("enabled", True):
        logger.error("sync.enabled = false，直连同步已禁用。")
        return

    try:
        code = run(cfg)
    except Exception:
        logger.exception("直连消费者异常退出")
        traceback.print_exc()
        code = 1
    finally:
        try:
            lock_sock.close()
        except Exception:
            pass
    sys.exit(code)


if __name__ == "__main__":
    main()
