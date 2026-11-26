# -*- coding: utf-8 -*-
"""回写器：把 AI 分析结果写回飞书

1. 回写「保险单」表：保险单号、批单号（按 record_id 更新）
2. 回写「工人保险清单」表：人员信息
   - 去重键 = 姓名 + 证件号码
   - 命中已有记录 → batch_update 替换
   - 未命中 → batch_create 新增
   - 状态 = 增保→正常，减保→失效
"""

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import (
    INSURANCE_POLICY_TABLE,
    WORKER_INSURANCE_TABLE,
    POLICY_NO_FIELD,
    BATCH_NO_FIELD,
    STATUS_FIELD,
)

logger = logging.getLogger(__name__)

# 飞书瞬时错误码：偶发，重试即可
#   1254045 FieldNameNotFound —— 实测批量 create 偶发，逐条重试必成功
#   1254607 Data not ready     —— 元信息未就绪
#   1254291 rate limited       —— 频率限制
_RETRYABLE_CODES = (1254045, 1254607, 1254291, 99991400)
_RETRY_TIMES = 3
_RETRY_BACKOFF = 1.5


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return code in _RETRYABLE_CODES


def _batch_with_fallback(op, records: List[dict], table_id: str,
                         label: str) -> List[dict]:
    """批量写入 + 降级：批量失败则退避重试，仍失败则逐条写入

    飞书 batch_create/batch_update 偶发返回 1254045 FieldNameNotFound，
    但同一条记录单独写入必定成功 —— 因此必须有逐条降级兜底。

    Returns:
        成功写入的记录列表；逐条阶段仍有失败时抛 RuntimeError（调用方据此记账）
    """
    if not records:
        return []
    try:
        return op(records, table_id=table_id)
    except Exception as e:
        if not _is_retryable(e):
            raise
        logger.warning("%s 批量失败(%s)，退避重试", label, e)
        for attempt in range(2, _RETRY_TIMES + 1):
            time.sleep(_RETRY_BACKOFF * attempt)
            try:
                return op(records, table_id=table_id)
            except Exception as e2:
                if not _is_retryable(e2):
                    raise
                logger.warning("%s 第 %d 次重试仍失败: %s", label, attempt, e2)

    # 逐条降级
    logger.warning("%s 降级为逐条写入（%d 条）", label, len(records))
    out: List[dict] = []
    failed: List[str] = []
    for rec in records:
        try:
            out.extend(op([rec], table_id=table_id))
        except Exception as e3:
            logger.error("%s 逐条写入失败 %s: %s", label,
                         rec.get("record_id", "?"), e3)
            failed.append(str(e3))
    if failed:
        raise RuntimeError("%s 逐条写入仍失败 %d/%d 条: %s"
                           % (label, len(failed), len(records), failed[:3]))
    return out


def to_date_millis(raw: Any) -> Optional[int]:
    """把日期值转成飞书日期字段接受的 13 位毫秒时间戳

    飞书日期字段（type=5）只接受 int 毫秒时间戳，传字符串报 1254064。
    支持 'YYYY-MM-DD' / 'YYYY/MM/DD' / 'YYYY.MM.DD' / 10 位秒 / 13 位毫秒。
    解析失败返回 None（该列不写入，避免污染）。
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        val = int(raw)
        return val * 1000 if val < 10_000_000_000 else val

    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("/", "-").replace(".", "-")
    # 去掉可能带的时间部分（日期字段只要日期）
    if " " in s:
        s = s.split(" ")[0]
    if "T" in s:
        s = s.split("T")[0]

    if s.isdigit() and len(s) in (10, 13):
        val = int(s)
        return val * 1000 if len(s) == 10 else val

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if not m:
        logger.warning("无法解析为日期，跳过该字段: %r", raw)
        return None
    try:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        logger.warning("非法日期，跳过该字段: %r", raw)
        return None
    return int(dt.timestamp() * 1000)


class PolicyWriter:
    def __init__(self, client: Any):
        self._client = client

    # ==================== 保险单表：保单号/批单号回写 ====================

    def write_policy_numbers(
        self,
        record_id: str,
        main_policy_number: str,
        batch_policy_number: str,
    ) -> bool:
        """回写「保险单」表的保险单号 / 批单号字段（仅写非空）"""
        fields: Dict[str, Any] = {}
        if main_policy_number:
            fields[POLICY_NO_FIELD] = main_policy_number
        if batch_policy_number:
            fields[BATCH_NO_FIELD] = batch_policy_number
        if not fields:
            logger.info("保单号/批单号均为空，跳过回写 record_id=%s", record_id)
            return False

        try:
            _batch_with_fallback(
                self._client.batch_update,
                [{"record_id": record_id, "fields": fields}],
                INSURANCE_POLICY_TABLE,
                "回写保险单号/批单号")
            logger.info("已回写保险单表 record_id=%s fields=%s", record_id, fields)
            return True
        except Exception as e:
            logger.exception("回写保险单表失败 record_id=%s: %s", record_id, e)
            return False

    # ==================== 工人保险清单表：人员回写（去重） ====================

    def write_persons(self, persons: List[dict], policy_info: Dict[str, Any],
                      index: Optional[Dict[str, List[str]]] = None) -> Dict[str, int]:
        """回写人员清单，返回 {"created": n, "updated": n}

        policy_info 需含：main_policy_number / batch_policy_number / policy_type /
        insurance_company / overall_start_date / overall_end_date

        index: 可选的外部索引 {去重键: [record_id, ...]}。
            ⚠️ 批量场景必须传入，否则每个文件都要拉一次全表（2482 条）建索引，
            N 个文件 = N 次全表扫描。传入后会就地增量维护（新增记录也写回索引）。
        """
        if not persons:
            return {"created": 0, "updated": 0}

        existing = index if index is not None else self._build_existing_index()

        to_create: List[tuple] = []   # (去重键, fields)
        to_update: List[dict] = []
        seen_keys = set()

        for p in persons:
            key = self._dedup_key(p)
            if not key:
                continue  # 姓名+证件号都为空，跳过
            fields = self._build_person_fields(p, policy_info)

            if key in existing:
                if key in seen_keys:
                    continue  # 同一批内重复（防重复新增）
                # 同一人可能有多条历史行 → 全部替换，保持数据一致
                for rid in existing[key]:
                    to_update.append({"record_id": rid, "fields": fields})
                if len(existing[key]) > 1:
                    logger.info(
                        "人员 %s 在表中已有 %d 条历史行，全部替换", key, len(existing[key])
                    )
            else:
                if key in seen_keys:
                    continue
                # ⚠️ 这里存**纯 fields**，不要包 {"fields": ...}：
                #    下面 batch_create 还会再包一层，双重包装会变成
                #    {"fields": {"fields": {...}}} → 飞书报 1254045 FieldNameNotFound
                to_create.append((key, fields))
            seen_keys.add(key)

        created = updated = 0
        new_records = []
        if to_create:
            try:
                new_records = _batch_with_fallback(
                    self._client.batch_create,
                    [{"fields": f} for _, f in to_create],
                    WORKER_INSURANCE_TABLE,
                    "批量新增人员")
                created = len(new_records)
            except Exception as e:
                logger.exception("批量新增人员失败: %s", e)
                created = -1   # -1 = 失败（区别于「确实 0 条」）
        if to_update:
            try:
                updated = len(_batch_with_fallback(
                    self._client.batch_update,
                    to_update,
                    WORKER_INSURANCE_TABLE,
                    "批量更新人员"))
            except Exception as e:
                logger.exception("批量更新人员失败: %s", e)
                updated = -1

        # 增量维护索引：把本批**实际写入成功**的人员写回，供下一批复用
        # （避免重复全表扫描）
        #
        # ⚠️ 绝不能对「创建失败」的 key 做 setdefault —— 那会让后续文件把
        #    表里根本不存在的记录误判为「已存在」，转而去 update 一个
        #    无效的 record_id，导致人员静默丢失。
        if index is not None:
            for (key, _), rec in zip(to_create, new_records or []):
                rid = (rec.get("record_id") or rec.get("id")) if isinstance(rec, dict) else None
                if rid:
                    existing.setdefault(key, [])
                    if rid not in existing[key]:
                        existing[key].append(rid)
            # 命中已有行（update）的 key 已在索引里，无需处理

        logger.info("人员回写完成：新增 %d，替换 %d", created, updated)
        stat = {"created": created, "updated": updated}
        if created < 0 or updated < 0:
            stat["error"] = "写入失败（详见日志）"
        return stat

    # ==================== 内部工具 ====================

    def _build_existing_index(self) -> Dict[str, List[str]]:
        """拉取工人保险清单全表，建立 姓名|证件号 → [record_id, ...] 索引

        ⚠️ 同一(姓名|证件号)可能有多条历史行（不同保单周期各一行，实测有 32 组）。
        因此索引存**列表**而非单个 record_id —— 否则只会更新第一条，
        留下另一条半新半旧的数据（保单号/状态不一致）。
        """
        index: Dict[str, List[str]] = {}
        try:
            records = self._client.list_records(WORKER_INSURANCE_TABLE, page_size=500)
        except Exception as e:
            logger.exception("拉取工人保险清单全表失败（去重降级为全量新增）: %s", e)
            return index

        for r in records:
            f = r.get("fields") or {}
            name = str(f.get("姓名", "") or "").strip()
            id_no = str(f.get("证件号码", "") or "").strip()
            key = self._dedup_key({"name": name, "id_number": id_no})
            if key:
                index.setdefault(key, []).append(r["record_id"])

        multi = {k: v for k, v in index.items() if len(v) > 1}
        logger.info(
            "工人保险清单去重索引：%d 个键（其中 %d 个键对应多条历史行）",
            len(index), len(multi),
        )
        return index

    @staticmethod
    def _dedup_key(p: dict) -> str:
        """去重键：姓名 + 证件号码；证件号为空则仅姓名"""
        name = str(p.get("name", "") or "").strip()
        id_no = str(p.get("id_number", "") or "").strip()
        if not name and not id_no:
            return ""
        return f"{name}|{id_no}"

    @staticmethod
    def _build_person_fields(p: dict, policy_info: Dict[str, Any]) -> Dict[str, Any]:
        """组装飞书「工人保险清单」表的字段（人员级 + 保单级）"""
        # 起始/终止时间：人员级优先，缺省用保单级保险期间兜底
        start = p.get("start_date") or policy_info.get("overall_start_date", "")
        end = p.get("end_date") or policy_info.get("overall_end_date", "")

        fields = {
            "姓名": p.get("name", ""),
            "证件号码": p.get("id_number", ""),
            "证件类型": p.get("id_type", "") or "身份证",
            "出生日期": p.get("birth_date", ""),
            "所属公司": p.get("company", ""),
            STATUS_FIELD: p.get("status", "正常"),
            # ⚠️ 起始时间 / 起止时间 已是**日期型字段**（type=5），
            #    必须传 13 位毫秒时间戳（int），传字符串报 1254064。
            "起始时间": to_date_millis(start),
            "起止时间": to_date_millis(end),
            "岗位名称": p.get("job_title", ""),
            "保险公司": policy_info.get("insurance_company", ""),
            "保单类型": policy_info.get("policy_type", ""),
            "保单号": policy_info.get("main_policy_number", ""),
            "批单号": policy_info.get("batch_policy_number", ""),
        }
        # 空值过滤：飞书不接受空字符串写入文本字段会保留空，但为干净起见仅保留非空
        return {k: v for k, v in fields.items() if v not in ("", None)}
