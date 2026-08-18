"""定时任务调度器

支持多个每日定时任务，每个任务在各自配置的时间点触发一次：
1. 打卡检查任务：同步打卡数据 → 检查保险覆盖 → 触发邮件提醒（sync_time）
2. 到期提醒任务：查询还有 N 天到期的人员保险 → 发邮件提醒续保（expiry_time）

配置项（存储在 data/scheduler_config.json）：
{
    "enabled": true,
    "sync_time": "08:00",          # 每日打卡检查时间
    "alert_enabled": true,         # 是否发送打卡提醒邮件
    "punch_sync_enabled": true,    # 是否启用「今日打卡数据同步」（关闭后不再从ERP拉取打卡，仅用现有数据做对比提醒）
    "expiry_time": "09:00",        # 到期提醒检查时间
    "expiry_ahead_days": 3,        # 提前 N 天提醒
    "expiry_enabled": true,        # 是否启用到期提醒
}
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from insurance_agent.infrastructure.paths import SCHEDULER_CONFIG_PATH

logger = logging.getLogger(__name__)

CONFIG_PATH = SCHEDULER_CONFIG_PATH

DEFAULT_CONFIG = {
    "enabled": True,
    "sync_time": "08:00",
    "alert_enabled": True,
    "punch_sync_enabled": True,
    "expiry_time": "09:00",
    "expiry_ahead_days": 3,
    "expiry_enabled": True,
}

# 全局调度器实例（供 web 层使用）
_scheduler: Optional["Scheduler"] = None


def load_scheduler_config() -> dict:
    """加载定时任务配置"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            merged = dict(DEFAULT_CONFIG)
            merged.update(cfg)
            return merged
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULT_CONFIG)


def save_scheduler_config(config: dict) -> bool:
    """保存定时任务配置（带重试，避免文件被短暂锁定导致失败）"""
    import time
    last_err = None
    for attempt in range(3):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            last_err = e
            time.sleep(0.3 * (attempt + 1))
    # 记录异常，便于排查（服务进程无 stdout）
    try:
        import traceback
        with open(os.path.join(os.path.dirname(CONFIG_PATH), "scheduler_save_error.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] {type(last_err).__name__}: {last_err}\n")
            traceback.print_exc(file=f)
    except Exception:
        pass
    return False


# 各任务上次执行日期持久化文件（避免服务重启后同一天重复触发定时任务/重复发邮件）
# 格式: {"daily_check": "2026-08-17", "expiry_reminder": "2026-08-17"}
STATE_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "scheduler_state.json")


def _load_state() -> dict:
    """加载各任务上次执行日期 {task_name: date}"""
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # 兼容旧格式 {"last_run_date": "..."}
                if "last_run_date" in data:
                    return {"daily_check": data.get("last_run_date")}
                return data
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_state(state: dict):
    """保存各任务上次执行日期"""
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


class Scheduler:
    """后台定时任务调度器

    支持多个每日定时任务，每个任务在各自配置的时间点每天触发一次。
    线程安全，可启停。
    """

    def __init__(self, check_interval: int = 60):
        """
        Args:
            check_interval: 检查间隔（秒），默认 60 秒
        """
        # 任务列表: [{"name": str, "callback": callable, "time_key": str}]
        self._tasks: list[dict] = []
        self._check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # 各任务上次执行日期，避免同一天重复执行；从文件加载，服务重启后不丢失
        self._last_run_dates: dict = _load_state()

    def add_task(self, name: str, callback: Callable, time_key: str = "sync_time"):
        """注册一个定时任务

        Args:
            name: 任务名（用于状态持久化去重，如 daily_check / expiry_reminder）
            callback: 到点触发的回调 callable() -> dict
            time_key: 从 scheduler_config.json 读取时间用的字段名
        """
        self._tasks.append({"name": name, "callback": callback, "time_key": time_key})
        logger.info("注册定时任务: %s (时间字段 %s)", name, time_key)

    # 兼容旧接口：主任务（daily_check）的上次执行日期
    @property
    def _last_run_date(self) -> Optional[str]:
        return self._last_run_dates.get("daily_check")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("定时任务调度器已启动")

    def stop(self):
        self._running = False
        logger.info("定时任务调度器已停止")

    def _loop(self):
        while self._running:
            try:
                config = load_scheduler_config()
                if config.get("enabled", True):
                    self._check_and_run(config)
            except Exception as e:
                logger.error("调度器循环异常: %s", e)
            # 等待（分片 sleep，便于及时响应 stop）
            for _ in range(self._check_interval):
                if not self._running:
                    return
                time.sleep(1)

    def _check_and_run(self, config: dict):
        """检查各任务是否到点，到点则执行对应任务"""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        for task in self._tasks:
            name = task["name"]
            time_key = task["time_key"]

            # 到期提醒任务有独立开关
            if name == "expiry_reminder" and not config.get("expiry_enabled", True):
                continue

            time_str = config.get(time_key, "08:00")
            try:
                h, m = map(int, time_str.split(":"))
            except (ValueError, AttributeError):
                continue

            target = now.replace(hour=h, minute=m, second=0, microsecond=0)

            # 当前时间在目标时间之后且今天还没执行过该任务
            if now >= target and self._last_run_dates.get(name) != today:
                self._last_run_dates[name] = today
                _save_state(self._last_run_dates)  # 持久化，避免服务重启后同一天重复触发
                logger.info("触发定时任务 %s: %s", name, time_str)
                try:
                    result = task["callback"]()
                    logger.info("任务 %s 执行结果: %s", name, result)
                except Exception as e:
                    logger.error("任务 %s 执行失败: %s", name, e)


def get_scheduler() -> Optional[Scheduler]:
    """获取全局调度器单例"""
    global _scheduler
    return _scheduler


def create_scheduler(task_callback: Optional[Callable] = None) -> Scheduler:
    """创建并注册全局调度器

    Args:
        task_callback: 主任务（daily_check 打卡检查）回调，可选。
                       后续可用 add_task 注册更多任务。
    """
    global _scheduler
    _scheduler = Scheduler()
    if task_callback is not None:
        _scheduler.add_task("daily_check", task_callback, "sync_time")
    return _scheduler
