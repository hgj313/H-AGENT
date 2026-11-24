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
from typing import Any, Dict, List

from .config import (
    INSURANCE_POLICY_TABLE,
    WORKER_INSURANCE_TABLE,
    POLICY_NO_FIELD,
    BATCH_NO_FIELD,
    STATUS_FIELD,
)

logger = logging.getLogger(__name__)


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
            self._client.batch_update(
                [{"record_id": record_id, "fields": fields}],
                table_id=INSURANCE_POLICY_TABLE,
            )
            logger.info("已回写保险单表 record_id=%s fields=%s", record_id, fields)
            return True
        except Exception as e:
            logger.exception("回写保险单表失败 record_id=%s: %s", record_id, e)
            return False

    # ==================== 工人保险清单表：人员回写（去重） ====================

    def write_persons(self, persons: List[dict], policy_info: Dict[str, Any]) -> Dict[str, int]:
        """回写人员清单，返回 {"created": n, "updated": n}

        policy_info 需含：main_policy_number / batch_policy_number / policy_type /
        insurance_company / overall_start_date / overall_end_date
        """
        if not persons:
            return {"created": 0, "updated": 0}

        existing = self._build_existing_index()

        to_create: List[dict] = []
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
                to_update.append({"record_id": existing[key], "fields": fields})
            else:
                if key in seen_keys:
                    continue
                to_create.append({"fields": fields})
            seen_keys.add(key)

        created = updated = 0
        if to_create:
            try:
                created = len(self._client.batch_create(to_create, table_id=WORKER_INSURANCE_TABLE))
            except Exception as e:
                logger.exception("批量新增人员失败: %s", e)
        if to_update:
            try:
                updated = len(self._client.batch_update(to_update, table_id=WORKER_INSURANCE_TABLE))
            except Exception as e:
                logger.exception("批量更新人员失败: %s", e)

        logger.info("人员回写完成：新增 %d，替换 %d", created, updated)
        return {"created": created, "updated": updated}

    # ==================== 内部工具 ====================

    def _build_existing_index(self) -> Dict[str, str]:
        """拉取工人保险清单全表，建立 姓名|证件号 → record_id 索引"""
        index: Dict[str, str] = {}
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
            if key and key not in index:
                index[key] = r["record_id"]
        logger.info("工人保险清单去重索引：%d 条", len(index))
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
            "起始时间": start,
            "起止时间": end,
            "岗位名称": p.get("job_title", ""),
            "保险公司": policy_info.get("insurance_company", ""),
            "保单类型": policy_info.get("policy_type", ""),
            "保单号": policy_info.get("main_policy_number", ""),
            "批单号": policy_info.get("batch_policy_number", ""),
        }
        # 空值过滤：飞书不接受空字符串写入文本字段会保留空，但为干净起见仅保留非空
        return {k: v for k, v in fields.items() if v not in ("", None)}
