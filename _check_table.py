# -*- coding: utf-8 -*-
"""检查飞书「今日打卡数据」表：总行数 + 指定身份证号的行数 + 最新几行。

用法：python _check_table.py [身份证号...]
"""
import json
import os
import sys

sys.path.insert(0, r"C:\insurance-automation")

from insurance_agent.infrastructure.feishu_bitable_client import load_client_from_config
from erp_feishu_direct.config import load_config

cfg = load_config()
fs = cfg["feishu"]
client = load_client_from_config(fs)
table_id = fs["table_id"]

recs = client.list_records(table_id)  # 尝试全量
if isinstance(recs, dict):
    items = recs.get("items") or recs.get("records") or []
else:
    items = recs or []

print("表 %s 总行数: %d" % (table_id, len(items)))

targets = sys.argv[1:]
if targets:
    for t in targets:
        hit = []
        for it in items:
            f = it.get("fields", {}) or {}
            if str(f.get("身份证号", "")).strip() == t:
                hit.append((it.get("record_id"), f))
        print("\n身份证号 %s -> %d 行" % (t, len(hit)))
        for rid, f in hit:
            print("  record_id=%s 姓名=%s 日期=%s 时间=%s 项目=%s"
                  % (rid, f.get("姓名"), f.get("打卡日期"), f.get("打卡时间"),
                     str(f.get("项目名称"))[:40]))

print("\n最后 5 行（按打卡时间排序取尾部）：")
def _ts(f):
    v = f.get("打卡时间")
    return v if isinstance(v, (int, float)) else 0
tail = sorted(items, key=lambda it: _ts(it.get("fields", {}) or {}))[-5:]
for it in tail:
    f = it.get("fields", {}) or {}
    print("  %s | %s | %s | %s" % (f.get("打卡时间"), f.get("姓名"),
                                   f.get("身份证号"), str(f.get("工种"))[:20]))
