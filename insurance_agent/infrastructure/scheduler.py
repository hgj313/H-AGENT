"""定时任务调度器

每天定时执行：同步打卡数据 → 检查保险覆盖 → 触发邮件提醒。

配置项（存储在 data/scheduler_config.json）：
{
    "enabled": true,
    "sync_time": "08:00",   # 每天同步时间
    "alert_enabled": true   # 是否发送提醒邮件
}
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Optional

from insurance_agent.infrastructure.paths import SCHEDULER_CONFIG_PATH

logger = logging.getLogger(__name__)

CONFIG_PATH = SCHEDULER_CONFIG_PATH

DEFAULT_CONFIG = {
    "enabled": True,
    "sync_time": "08:00",
    "alert_enabled": True,
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


# 上次执行日期持久化文件（避免服务重启后同一天重复触发定时任务/重复发邮件）
STATE_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "scheduler_state.json")


def _load_last_run_date() -> Optional[str]:
    """加载上次执行日期"""
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("last_run_date")
        except (json.JSONDecodeError, IOError):
            pass
    return None


def _save_last_run_date(date_str: str):
    """保存上次执行日期"""
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"last_run_date": date_str}, f)
    except Exception:
        pass


class Scheduler:
    """后台定时任务调度器

    每天到配置的时间点触发一次任务回调。
    线程安全，可启停。
    """

    def __init__(self, task_callback, check_interval: int = 60):
        """
        Args:
            task_callback: 到点触发的回调函数 callable() -> dict
            check_interval: 检查间隔（秒），默认 60 秒
        """
        self._task_callback = task_callback
        self._check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # 上次执行日期，避免同一天重复执行；从文件加载，服务重启后不丢失
        self._last_run_date: Optional[str] = _load_last_run_date()

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
            # 等待
            for _ in range(self._check_interval):
                if not self._running:
                    return
                import time
                time.sleep(1)

    def _check_and_run(self, config: dict):
        """检查是否到点，到点则执行任务"""
        now = datetime.now()
        sync_time = config.get("sync_time", "08:00")
        today = now.strftime("%Y-%m-%d")

        try:
            h, m = map(int, sync_time.split(":"))
        except (ValueError, AttributeError):
            return

        target = now.replace(hour=h, minute=m, second=0, microsecond=0)

        # 当前时间在目标时间之后且今天还没执行过
        if now >= target and self._last_run_date != today:
            self._last_run_date = today
            _save_last_run_date(today)  # 持久化，避免服务重启后同一天重复触发
            logger.info("触发定时任务: %s", sync_time)
            try:
                result = self._task_callback()
                logger.info("定时任务执行结果: %s", result)
            except Exception as e:
                logger.error("定时任务执行失败: %s", e)


def get_scheduler() -> Scheduler:
    """获取全局调度器单例"""
    global _scheduler
    return _scheduler


def create_scheduler(task_callback) -> Scheduler:
    """创建并注册全局调度器"""
    global _scheduler
    _scheduler = Scheduler(task_callback)
    return _scheduler
