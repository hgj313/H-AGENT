# -*- coding: utf-8 -*-
"""工人保险清单「起始时间」「起止时间」文本 → 日期字段 迁移

为什么不能直接改字段类型
------------------------
飞书官方明确：**「字段类型的更改使原本的内容失效（清空）」**。
直接 PUT fields/{field_id} 改 type=1→5，已有 2481 条的日期文本会被清空，
且 API 层没有 UI 那个「尝试自动转换」选项。

安全做法（新建 → 回填 → 删旧）
------------------------------
1. 备份全表字段值（含起始/起止两列原文）到 JSON
2. 新建两个日期字段（type=5），临时名「起始时间(日期)」「起止时间(日期)」
3. 把两列文本解析成毫秒时间戳，batch_update 回填到新字段
4. 校验：新字段非空条数 == 旧字段非空条数，且抽样比对日期一致
5. 删掉两个旧文本字段
6. 把新字段改名回「起始时间」「起止时间」

⚠️ 步骤 5 之后旧字段名释放，改名才成功；顺序不可颠倒。

用法::

    python -m policy_analysis.migrate_date_fields --dry-run   # 只探查+备份，不改表
    python -m policy_analysis.migrate_date_fields --apply     # 真正迁移
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import WORKER_INSURANCE_TABLE, load_feishu_config

BACKUP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "_backup_date_migration.json",
)

# 迁移的目标字段
TARGETS = [
    # (旧字段名, 临时字段名, 显示格式)
    ("起始时间", "起始时间(日期)", "yyyy-MM-dd"),
    ("起止时间", "起止时间(日期)", "yyyy-MM-dd"),
]


def parse_to_millis(raw) -> int:
    """把 '2026/10/18' / '2026-11-22' 解析成当天零点的毫秒时间戳"""
    s = str(raw or "").strip()
    if not s:
        return 0
    s = s.replace("/", "-").replace(".", "-")
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if not m:
        return 0
    try:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return 0
    return int(dt.timestamp() * 1000)


def millis_to_str(ms) -> str:
    """毫秒时间戳 → 'YYYY-MM-DD'（仅用于校验比对）"""
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from insurance_agent.infrastructure.feishu_bitable_client import load_client_from_config

    client = load_client_from_config(load_feishu_config())

    # ---------- 1. 备份 ----------
    fields = client.list_fields(WORKER_INSURANCE_TABLE)
    field_by_name = {f["field_name"]: f for f in fields}
    for old, tmp, _fmt in TARGETS:
        if old not in field_by_name:
            print("❌ 表中找不到字段「%s」，终止" % old)
            return
        print("字段「%s」当前 type=%s field_id=%s" % (
            old, field_by_name[old].get("type"), field_by_name[old].get("field_id")))

    records = client.list_records(WORKER_INSURANCE_TABLE, page_size=500)
    backup = {
        "table_id": WORKER_INSURANCE_TABLE,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fields": {old: field_by_name[old].get("field_id") for old, _t, _f in TARGETS},
        "records": [
            {
                "record_id": r["record_id"],
                "fields": {old: (r.get("fields") or {}).get(old, "") for old, _t, _f in TARGETS},
            }
            for r in records
        ],
    }
    with open(BACKUP_PATH, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)
    print("\n已备份 %d 条 → %s" % (len(backup["records"]), BACKUP_PATH))

    # ---------- 2. 解析预检 ----------
    bad = 0
    parsed_total = 0
    for r in records:
        fl = r.get("fields") or {}
        for old, _t, _f in TARGETS:
            v = fl.get(old)
            if v is None or str(v).strip() == "":
                continue
            ms = parse_to_millis(v)
            if ms:
                parsed_total += 1
            else:
                bad += 1
                if bad <= 5:
                    print("  ⚠️ 无法解析: record_id=%s %s=%r" % (r["record_id"], old, v))
    print("可解析日期值: %d，无法解析: %d" % (parsed_total, bad))
    if bad:
        print("❌ 存在无法解析的值，中止（不改动表结构）")
        return

    if args.dry_run:
        print("\n[dry-run] 探查完成，未改动表结构。")
        return

    # ---------- 3. 新建日期字段 ----------
    created = {}
    for old, tmp, fmt in TARGETS:
        if tmp in field_by_name:
            # 上次中断遗留 → 复用
            created[old] = field_by_name[tmp]
            print("字段「%s」已存在，复用 field_id=%s" % (tmp, field_by_name[tmp]["field_id"]))
            continue
        res = client._request(
            "POST",
            "/bitable/v1/apps/%s/tables/%s/fields" % (client._app_token, WORKER_INSURANCE_TABLE),
            json_body={
                "field_name": tmp,
                "type": 5,
                "property": {"date_formatter": fmt, "auto_fill": False},
            },
        )
        fld = res.get("field") or {}
        created[old] = fld
        print("已新建日期字段「%s」field_id=%s" % (tmp, fld.get("field_id")))

    # ---------- 4. 回填 ----------
    for old, tmp, _fmt in TARGETS:
        payload = []
        for r in records:
            fl = r.get("fields") or {}
            v = fl.get(old)
            if v is None or str(v).strip() == "":
                continue
            ms = parse_to_millis(v)
            if ms:
                payload.append({"record_id": r["record_id"], "fields": {tmp: ms}})
        updated = client.batch_update(payload, table_id=WORKER_INSURANCE_TABLE)
        print("回填「%s」→「%s」: %d 条" % (old, tmp, len(updated)))

    # ---------- 5. 校验 ----------
    recs2 = client.list_records(WORKER_INSURANCE_TABLE, page_size=500)
    ok = True
    for old, tmp, _fmt in TARGETS:
        src_nonempty = 0
        dst_nonempty = 0
        mismatch = 0
        for r in recs2:
            fl = r.get("fields") or {}
            sv = fl.get(old)
            dv = fl.get(tmp)
            if sv is None or str(sv).strip() == "":
                continue
            src_nonempty += 1
            if dv in (None, ""):
                continue
            dst_nonempty += 1
            if millis_to_str(dv) != parse_to_millis(sv) and \
               datetime.fromtimestamp(int(dv) / 1000).strftime("%Y-%m-%d") != \
               datetime.fromtimestamp(parse_to_millis(sv) / 1000).strftime("%Y-%m-%d"):
                mismatch += 1
        print("校验「%s」→「%s」: 源非空 %d，目标非空 %d，不一致 %d" % (
            old, tmp, src_nonempty, dst_nonempty, mismatch))
        if src_nonempty != dst_nonempty or mismatch:
            ok = False

    if not ok:
        print("\n❌ 校验未通过，**中止**（旧字段仍保留，数据未丢）")
        return

    # ---------- 6. 删旧字段 ----------
    for old, tmp, _fmt in TARGETS:
        fid = field_by_name[old]["field_id"]
        try:
            client._request(
                "DELETE",
                "/bitable/v1/apps/%s/tables/%s/fields/%s" % (
                    client._app_token, WORKER_INSURANCE_TABLE, fid),
            )
            print("已删除旧字段「%s」field_id=%s" % (old, fid))
        except Exception as e:
            print("❌ 删除旧字段「%s」失败: %s" % (old, e))
            return

    # ---------- 7. 新字段改名回原名 ----------
    for old, tmp, _fmt in TARGETS:
        fid = (created[old] or {}).get("field_id")
        if not fid:
            print("❌ 缺少新字段 field_id，无法改名")
            return
        try:
            client._request(
                "PUT",
                "/bitable/v1/apps/%s/tables/%s/fields/%s" % (
                    client._app_token, WORKER_INSURANCE_TABLE, fid),
                json_body={
                    "field_name": old,
                    "type": 5,
                    "property": {"date_formatter": "yyyy-MM-dd", "auto_fill": False},
                },
            )
            print("已改名「%s」→「%s」" % (tmp, old))
        except Exception as e:
            print("❌ 改名失败 %s→%s: %s" % (tmp, old, e))
            return

    # ---------- 8. 最终确认 ----------
    print("\n=== 最终字段结构 ===")
    for f in client.list_fields(WORKER_INSURANCE_TABLE):
        mark = " ← 日期" if f.get("type") == 5 else ""
        print("  %-14s type=%s%s" % (f.get("field_name"), f.get("type"), mark))

    recs3 = client.list_records(WORKER_INSURANCE_TABLE, page_size=500)
    sample = None
    for r in recs3:
        fl = r.get("fields") or {}
        if fl.get("起始时间"):
            sample = fl
            break
    if sample:
        print("\n抽样记录: 起始=%r 起止=%r" % (
            sample.get("起始时间"), sample.get("起止时间")))
        for k in ("起始时间", "起止时间"):
            v = sample.get(k)
            if v:
                print("  %s 显示为 %s" % (k, datetime.fromtimestamp(int(v) / 1000).strftime("%Y-%m-%d")))


if __name__ == "__main__":
    main()
