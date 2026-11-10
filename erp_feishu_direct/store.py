"""幂等映射存储：打卡日期 + 身份证号 → 飞书 record_id

不落 SQLite，只用一个轻量 JSON 文件。

为什么需要它
------------
ERP 的 MQ 消息可能重复投递（网络重试、消费者重启、消息重投），
同一天同一人的打卡若重复新增，飞书表里就会出现重复行。
维护 (日期, 身份证号) → record_id 的映射后：
- 首次收到 → batch_create，拿到 record_id 存下来
- 再次收到 → batch_update，同一行被更新，不会重复

文件结构::

    {
      "2026-11-10": {
        "452428196708182024": "recXXXXXX"
      }
    }

按天分桶，过期日期自动清理（默认保留 7 天），防止文件无限增长。
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SyncMapStore:
    """幂等映射存储（线程安全，原子写盘）"""

    def __init__(self, path: str, keep_days: int = 7):
        self._path = path
        self._keep_days = keep_days
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, str]] = {}
        self._load()

    # ==================== 读写 ====================

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._data = {
                    k: v for k, v in data.items() if isinstance(v, dict)
                }
                logger.info("已加载幂等映射: %s（%d 天）", self._path, len(self._data))
        except Exception as e:  # noqa: BLE001
            logger.warning("加载幂等映射失败，从空开始: %s", e)
            self._data = {}

    def _save(self) -> None:
        """原子写盘：先写临时文件再替换，避免进程中断留下半截 JSON"""
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception as e:  # noqa: BLE001
            logger.error("保存幂等映射失败: %s", e)

    # ==================== 对外接口 ====================

    def get_record_id(self, punch_date: str, id_number: str) -> Optional[str]:
        """查某天某人的飞书 record_id；不存在返回 None"""
        with self._lock:
            return self._data.get(punch_date, {}).get(id_number)

    def set_record_id(self, punch_date: str, id_number: str, record_id: str) -> None:
        """记录映射并落盘"""
        with self._lock:
            self._data.setdefault(punch_date, {})[id_number] = record_id
            self._cleanup_locked()
            self._save()

    def set_many(self, punch_date: str, pairs: Dict[str, str]) -> None:
        """批量记录映射（一次落盘，减少 IO）"""
        if not pairs:
            return
        with self._lock:
            day = self._data.setdefault(punch_date, {})
            day.update(pairs)
            self._cleanup_locked()
            self._save()

    def get_day_map(self, punch_date: str) -> Dict[str, str]:
        """取某天的完整映射"""
        with self._lock:
            return dict(self._data.get(punch_date, {}))

    def _cleanup_locked(self) -> None:
        """清理过期日期（调用方需已持锁）"""
        if self._keep_days <= 0:
            return
        cutoff = (datetime.now() - timedelta(days=self._keep_days)).strftime("%Y-%m-%d")
        expired = [d for d in self._data if d < cutoff]
        for d in expired:
            del self._data[d]
        if expired:
            logger.debug("清理过期映射日期: %s", expired)

    def stats(self) -> dict:
        """统计信息（给状态接口用）"""
        with self._lock:
            return {
                "path": self._path,
                "days": len(self._data),
                "total_records": sum(len(v) for v in self._data.values()),
                "keep_days": self._keep_days,
            }
