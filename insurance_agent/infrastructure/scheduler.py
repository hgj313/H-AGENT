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

logger = logging.getLogger(__name__)

DATA_DIR = "C:/insurance-automation/data"
CONFIG_PATH = os.path.join(DATA_DIR, "scheduler_config.json")

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
    """保存定时任务配置"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


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
        self._last_run_date: Optional[str] = None  # 上次执行日期，避免同一天重复执行

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
