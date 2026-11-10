"""飞书多维表格写入器（直连链路专用）

复用 `insurance_agent.infrastructure.feishu_bitable_client.FeishuBitableClient`
—— 那是纯 HTTP 客户端，不依赖任何业务逻辑与数据库，适合在独立进程里复用。

本模块负责：
- 把一批事件按幂等规则拆成「新增」与「更新」两组
- 批量写入（每批 ≤500 条）
- 新增成功后回写 record_id 映射（幂等的核心）
- 失败重试 + DLQ 落盘
"""

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from insurance_agent.infrastructure.feishu_bitable_client import (
    FeishuBitableClient,
    FeishuBitableError,
)

from erp_feishu_direct.config import DLQ_PATH
from erp_feishu_direct.mapper import build_fields, extract_punch_date
from erp_feishu_direct.store import SyncMapStore

logger = logging.getLogger(__name__)


class FeishuWriter:
    """把打卡事件批量写入飞书多维表格"""

    def __init__(
        self,
        client: FeishuBitableClient,
        store: SyncMapStore,
        field_mapping: Optional[Dict[str, str]] = None,
        table_id: str = "",
        max_batch_size: int = 500,
        retry: int = 3,
        retry_backoff: float = 2.0,
        dlq_path: str = DLQ_PATH,
    ):
        self._client = client
        self._store = store
        self._mapping = field_mapping
        self._table_id = table_id
        self._max_batch = min(max_batch_size, 500)
        self._retry = retry
        self._retry_backoff = retry_backoff
        self._dlq_path = dlq_path

        self._stats = {
            "received": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
        }

    # ==================== 主入口 ====================

    def write_batch(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """写入一批事件

        Returns:
            {"created": N, "updated": N, "skipped": N, "failed": N}
        """
        if not events:
            return {"created": 0, "updated": 0, "skipped": 0, "failed": 0}

        self._stats["received"] += len(events)

        # 1) 拆成 待新增 / 待更新 / 跳过
        create_rows: List[Tuple[str, str, dict]] = []  # (punch_date, id_number, fields)
        to_update: List[dict] = []  # {"record_id", "fields"}
        skipped = 0

        for ev in events:
            id_num = str(ev.get("identificationNumber") or "").strip()
            if not id_num:
                skipped += 1
                continue

            fields = build_fields(ev, self._mapping)
            if not fields:
                skipped += 1
                continue

            punch_date = extract_punch_date(ev)
            record_id = self._store.get_record_id(punch_date, id_num)
            if record_id:
                to_update.append({"record_id": record_id, "fields": fields})
            else:
                create_rows.append((punch_date, id_num, fields))

        created_n = 0
        updated_n = 0
        failed_n = 0

        # 2) 更新已有记录
        if to_update:
            ok, n = self._do_batch(
                lambda chunk: self._client.batch_update(chunk, table_id=self._table_id),
                to_update,
                "更新",
            )
            if ok:
                updated_n = n
            else:
                failed_n += len(to_update)

        # 3) 新增记录 + 回写 record_id 映射
        if create_rows:
            payloads = [{"fields": f} for _d, _i, f in create_rows]
            ok, results = self._do_batch(
                lambda chunk: self._client.batch_create(chunk, table_id=self._table_id),
                payloads,
                "新增",
                collect_results=True,
            )
            if ok:
                created_n = len(create_rows)
                # 回写映射：batch_create 返回顺序与入参顺序一致
                self._remember_ids(create_rows, results)
            else:
                failed_n += len(create_rows)

        self._stats["created"] += created_n
        self._stats["updated"] += updated_n
        self._stats["skipped"] += skipped
        self._stats["failed"] += failed_n

        return {
            "created": created_n,
            "updated": updated_n,
            "skipped": skipped,
            "failed": failed_n,
        }

    # ==================== 内部实现 ====================

    def _do_batch(
        self,
        api_call: Callable[[List], List],
        items: List,
        action: str,
        collect_results: bool = False,
    ) -> Tuple[bool, Any]:
        """执行批量写入（自动分批 + 重试 + DLQ）

        Args:
            api_call: 调用飞书的函数，入参为一个 chunk
            items: 待写入条目
            action: "新增" / "更新"（用于日志与 DLQ 标记）
            collect_results: 是否收集飞书返回值（新增场景需要 record_id）

        Returns:
            (是否全部成功, 成功条数或返回值列表)
        """
        if not items:
            return True, [] if collect_results else 0

        total_ok = 0
        all_results: List = []
        failed_items: List = []

        for i in range(0, len(items), self._max_batch):
            chunk = items[i : i + self._max_batch]
            ok, results, err = self._call_with_retry(api_call, chunk, action)
            if ok:
                total_ok += len(results or [])
                if collect_results:
                    all_results.extend(results or [])
            else:
                failed_items.extend(chunk)
                logger.error("%s失败 %d 条: %s", action, len(chunk), err)

        if failed_items:
            self._write_dlq(failed_items, action)

        return (not failed_items), (all_results if collect_results else total_ok)

    def _call_with_retry(
        self, api_call: Callable[[List], List], chunk: List, action: str
    ) -> Tuple[bool, List, str]:
        """带指数退避的重试调用

        业务错误（如字段名不存在 1254045）重试无意义，直接判失败。
        """
        last_err = ""
        for attempt in range(1, self._retry + 1):
            try:
                result = api_call(chunk)
                return True, result or [], ""
            except FeishuBitableError as e:
                last_err = str(e)
                # code != -1 表示飞书返回了明确的业务错误码，重试无意义
                if e.code is not None and e.code != -1:
                    logger.warning("%s业务错误，不再重试: %s", action, last_err)
                    return False, [], last_err
                logger.warning("%s第 %d/%d 次失败: %s", action, attempt, self._retry, last_err)
            except Exception as e:  # noqa: BLE001
                last_err = repr(e)
                logger.warning("%s第 %d/%d 次异常: %s", action, attempt, self._retry, last_err)

            if attempt < self._retry:
                time.sleep(self._retry_backoff * (2 ** (attempt - 1)))

        return False, [], last_err

    def _remember_ids(self, create_rows: List[Tuple[str, str, dict]], results: List) -> None:
        """新增成功后回写 record_id 映射

        飞书 batch_create 的返回 records 顺序与请求 records 顺序一致，
        因此可按下标配对 (punch_date, id_number) → record_id。
        """
        if not results:
            logger.warning("新增成功但未返回 record_id，映射未回写（下次会重复新增）")
            return

        pairs: Dict[str, Dict[str, str]] = {}
        for (punch_date, id_num, _fields), rec in zip(create_rows, results):
            rid = (rec or {}).get("record_id")
            if rid:
                pairs.setdefault(punch_date, {})[id_num] = rid

        for punch_date, day_pairs in pairs.items():
            self._store.set_many(punch_date, day_pairs)

        if len(pairs) < len(create_rows):
            logger.warning(
                "映射回写不完整: %d/%d 条拿到 record_id",
                sum(len(v) for v in pairs.values()), len(create_rows),
            )

    def _write_dlq(self, items: List, action: str) -> None:
        """失败记录落 DLQ（JSONL，可人工重放）"""
        try:
            with open(self._dlq_path, "a", encoding="utf-8") as f:
                for it in items:
                    f.write(json.dumps({
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "action": action,
                        "payload": it,
                    }, ensure_ascii=False) + "\n")
            logger.error("已写入 DLQ: %s（%d 条）", self._dlq_path, len(items))
        except Exception as e:  # noqa: BLE001
            logger.error("写 DLQ 失败: %s", e)

    # ==================== 状态 ====================

    def stats(self) -> dict:
        return dict(self._stats)
