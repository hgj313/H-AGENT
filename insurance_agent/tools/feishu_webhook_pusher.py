"""飞书多维表格 Webhook 推送器（保险管理AI助手）

作用
----
把"今日打卡无正常保单"的人员数据实时同步到飞书多维表格的指定记录里。
本服务（8765）作为出站调用方，主动 POST 到飞书多维表格的自动化 webhook，
由飞书侧的"自动化流程"执行"添加记录"等操作。

设计要点
----
1. **异步队列 + 单 worker 线程**：不影响主流程（实时打卡消费/定时汇总）。
2. **Bearer Token 鉴权**：Authorization Header 固定前缀 `Bearer ` + 1 个空格。
3. **重试 + 死信队列**：业务错误（凭证错/IP 拦截）不重试直接落 DLQ；网络异常按指数退避重试。
4. **幂等 Client-Token**：用 (id_number + project_name + punch_date) SHA1 作为飞书幂等键，
   飞书侧 3 小时内同值只触发一次，避免重复添加。
5. **配置热加载**：编辑 .feishu_webhook.json 后下次 push 自动读新值，无需重启服务。

数据流
----
realtime_punch_consumer / uninsured_summary
  ↓ push(person_dict)
FeishuWebhookPusher（异步队列）
  ↓ POST Authorization: Bearer <token>
飞书多维表格 webhook
  ↓ 触发自动化流程
飞书多维表格（添加记录）
"""

import hashlib
import json
import logging
import os
import queue
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Dict, Optional

import requests

logger = logging.getLogger("feishu_webhook_pusher")

# 配置 / DLQ 路径
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(_BASE_DIR, ".feishu_webhook.json")
DLQ_PATH = os.path.join(_BASE_DIR, "feishu_webhook_dlq.jsonl")
LOG_PATH = os.path.join(_BASE_DIR, "feishu_webhook_pusher.log")

# 模块级状态：单例 pusher（由 server.py 启动时初始化，其他模块直接 import 复用）
_pusher_instance: Optional["FeishuWebhookPusher"] = None
_pusher_lock = threading.Lock()


def _log(msg: str) -> None:
    """统一日志：写文件 + 控制台。"""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    logger.info("[feishu-webhook] %s", msg)


def _make_client_token(person: dict) -> str:
    """生成飞书幂等键。

    飞书规则：相同 Client-Token 在 3 小时内只触发一次自动化流程。
    用 (id_number + project_name + punch_date) SHA1 保证同人同项目同日不重复。
    """
    raw = f"{person.get('id_number', '')}|{person.get('project_name', '')}|{person.get('punch_date', '')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class FeishuWebhookPusher:
    """飞书多维表格 webhook 异步推送器（线程安全单例）"""

    def __init__(self, config_path: str = CONFIG_PATH):
        self.config_path = config_path
        self.config = self._load_config()
        self._queue: "queue.Queue" = queue.Queue(maxsize=10000)
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="feishu-pusher",
        )
        self._stats = {
            "enqueued": 0,
            "sent_ok": 0,
            "sent_fail": 0,
            "dlq_count": 0,
            "last_sent_at": None,
            "last_error": None,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._worker.start()
        _log(
            f"飞书 webhook pusher 启动 | enabled={self.config.get('enabled')} "
            f"url={self.config.get('webhook_url', '')[:60]}..."
        )

    @staticmethod
    def _load_config(path: str = None) -> dict:
        """加载 .feishu_webhook.json，文件不存在/JSON 错时回退默认关闭配置。"""
        path = path or CONFIG_PATH
        if not os.path.exists(path):
            return {"enabled": False, "webhook_url": "", "bearer_token": ""}
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                return {"enabled": False, "webhook_url": "", "bearer_token": ""}
            return cfg
        except Exception as e:
            _log(f"加载配置失败，回退默认: {e}")
            return {"enabled": False, "webhook_url": "", "bearer_token": ""}

    def reload_config(self) -> dict:
        """热加载配置（外部修改 .feishu_webhook.json 后可调用）。"""
        with _pusher_lock:
            self.config = self._load_config(self.config_path)
            _log(f"配置已重载: enabled={self.config.get('enabled')}")
            return self.config

    def push(self, payload: dict, source: str = "realtime") -> bool:
        """主线程调用：把一条记录丢进异步队列，立即返回（非阻塞）。"""
        cfg = self.config
        if not cfg.get("enabled", False):
            return False
        if not cfg.get("bearer_token") or cfg.get("bearer_token") == "_YOUR_NEW_TOKEN_HERE_":
            _log(f"[{source}] bearer_token 未配置，跳过推送")
            return False
        try:
            self._queue.put_nowait((payload, source))
            self._stats["enqueued"] += 1
            return True
        except queue.Full:
            _log(f"[{source}] 推送队列已满，丢弃本条")
            self._stats["sent_fail"] += 1
            return False

    def push_batch(self, payloads: list, source: str = "summary") -> int:
        """批量入队，返回成功入队条数。"""
        ok = 0
        for p in payloads:
            if self.push(p, source=source):
                ok += 1
        return ok

    def _run(self):
        """worker 线程主循环：从队列取 payload → 推送（重试）→ 落 DLQ。"""
        while not self._stop.is_set():
            try:
                payload, source = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._push_with_retry(payload, source)
            except Exception as e:
                _log(f"[{source}] worker 异常: {e}\n{traceback.format_exc()}")
                self._stats["sent_fail"] += 1

    def _push_with_retry(self, payload: dict, source: str):
        cfg = self.config
        url = cfg.get("webhook_url", "")
        token = cfg.get("bearer_token", "")
        timeout = int(cfg.get("timeout", 5))
        max_retries = int(cfg.get("max_retries", 3))

        if not url or not token:
            _log(f"[{source}] URL 或 Token 为空，跳过")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",  # 显式声明 UTF-8，避免被中间网关按 GBK 兜底
            "Client-Token": _make_client_token(payload),  # 幂等
        }
        # 显式 ensure_ascii=False 避免中文被转义成 \uXXXX（部分网关对转义序列二次解码会出错）
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    url,
                    data=body_bytes,
                    headers=headers,
                    timeout=timeout,
                )
                # 飞书返回 200 但 code!=0 是业务错误（如 800005649 凭证错、800005650 IP 不在白名单）
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        data = {"code": -1, "msg": f"非 JSON 响应: {resp.text[:200]}"}
                    if data.get("code") == 0:
                        self._stats["sent_ok"] += 1
                        self._stats["last_sent_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        _log(
                            f"[{source}] 推送成功 | client_token={headers['Client-Token'][:12]}... | "
                            f"name={payload.get('name', '')}"
                        )
                        return
                    # 业务错误：不重试，落 DLQ
                    err_code = data.get("code")
                    err_msg = data.get("msg", "")
                    last_error = f"code={err_code} msg={err_msg}"
                    _log(f"[{source}] 飞书业务错误 {last_error} (落 DLQ, 不再重试)")
                    self._stats["last_error"] = last_error
                    self._write_dlq(payload, source, last_error)
                    self._stats["sent_fail"] += 1
                    return
                # HTTP 非 200：可能是限流/服务端异常，可重试
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                _log(f"[{source}] 第 {attempt + 1} 次失败: {last_error}")
            except (requests.Timeout, requests.ConnectionError) as e:
                last_error = f"网络异常: {e}"
                _log(f"[{source}] 第 {attempt + 1} 次网络异常: {e}")
            except Exception as e:
                last_error = f"未知异常: {e}"
                _log(f"[{source}] 第 {attempt + 1} 次异常: {e}\n{traceback.format_exc()}")
                break
            # 指数退避 1s / 2s / 4s ...
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

        # 重试耗尽 → DLQ
        _log(f"[{source}] 重试 {max_retries} 次耗尽，落 DLQ: {last_error}")
        self._write_dlq(payload, source, last_error or "未知失败")
        self._stats["sent_fail"] += 1

    def _write_dlq(self, payload: dict, source: str, reason: str):
        """失败记录落 DLQ（JSONL 格式，可手动重放）。"""
        record = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "payload": payload,
            "reason": reason,
        }
        try:
            with open(DLQ_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._stats["dlq_count"] += 1
        except Exception as e:
            _log(f"写 DLQ 失败: {e}")

    def get_status(self, mask_token: bool = True) -> dict:
        """返回 pusher 状态（给管理 API 用）。"""
        cfg = self.config.copy()
        if mask_token and cfg.get("bearer_token"):
            t = cfg["bearer_token"]
            cfg["bearer_token"] = (t[:4] + "***" + t[-4:]) if len(t) > 8 else "***"
        return {
            "config": cfg,
            "stats": self._stats,
            "queue_size": self._queue.qsize(),
            "worker_alive": self._worker.is_alive(),
            "dlq_path": DLQ_PATH,
            "log_path": LOG_PATH,
        }

    def stop(self, timeout: float = 3.0):
        """停止 worker（一般用于测试或服务关闭）。"""
        self._stop.set()
        self._worker.join(timeout=timeout)


# ============ 单例管理 ============

def init_pusher(config_path: str = CONFIG_PATH) -> FeishuWebhookPusher:
    """服务启动时初始化单例（在 server.py startup_event 调用）。"""
    global _pusher_instance
    with _pusher_lock:
        if _pusher_instance is None:
            _pusher_instance = FeishuWebhookPusher(config_path)
        return _pusher_instance


def get_pusher() -> Optional[FeishuWebhookPusher]:
    """获取单例（未初始化时返回 None）。"""
    return _pusher_instance


def push_uninsured_person(person: dict, source: str = "realtime") -> bool:
    """便捷函数：推送一条无保险人员记录。

    Args:
        person: 人员字典（与 realtime_punch_consumer / uninsured_summary 输出一致），
                字段包含 name/id_number/project_name/team_name/supplier_name/
                category_name/project_manager/manager_phone/manager_email/punch_time
        source: 来源标识（"realtime" / "summary_morning" / "summary_afternoon"）
    """
    p = get_pusher()
    if p is None:
        # 自动兜底：未显式初始化就尝试建一次
        p = init_pusher()
    # 自动补 punch_date（幂等键需要）
    if "punch_date" not in person:
        person = dict(person)
        person["punch_date"] = datetime.now().strftime("%Y-%m-%d")
    return p.push(person, source=source)


def push_uninsured_summary(persons: list, source: str = "summary", punch_date: str = None) -> int:
    """便捷函数：批量推送未参保人员（汇总任务用）。"""
    if not persons:
        return 0
    punch_date = punch_date or datetime.now().strftime("%Y-%m-%d")
    payload_list = []
    for p in persons:
        p2 = dict(p)
        p2.setdefault("punch_date", punch_date)
        payload_list.append(p2)
    p = get_pusher() or init_pusher()
    return p.push_batch(payload_list, source=source)
