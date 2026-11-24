# -*- coding: utf-8 -*-
"""工人保险清单 重复行清理（同一人多条历史行 → 保留最新一条）

背景
----
历史上同一个人（姓名+证件号相同）在「工人保险清单」表里会留多行：
每一轮保单续期就新增一行，旧行不删。实测 32 组 / 64 条，
每组两行分别是「上一保单周期」与「本保单周期」。

问题
----
1. 数据重复 —— 同一个工人在表里出现两次，统计人数会翻倍；
2. 去重键冲突 —— 写入时按 姓名|证件号 匹配，若只更新第一条，
   另一条会留着旧的保单号/状态/起止期，半新半旧。

处理策略
--------
每组保留**起始时间最新**的那一行，其余行**删除**。
判定「最新」：起始时间字符串归一化后取最大（兼容 `2026/10/18` 与 `2026-11-18` 两种写法）。

⚠️ 破坏性操作，默认 dry-run；`--apply` 才真删。
执行前自动备份被删行的完整内容。

用法::

    python -m policy_analysis.dedup_workers --dry-run
    python -m policy_analysis.dedup_workers --apply
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import WORKER_INSURANCE_TABLE, load_feishu_config

BACKUP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "_backup_dedup_workers.json",
)


def _norm_date(raw) -> str:
    """日期归一化：`2026/10/18` / `2026-11-18` → `2026-11-18`；空串排最后"""
    s = str(raw or "").strip()
    if not s:
        return "0000-00-00"
    s = s.replace("/", "-").replace(".", "-")
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from insurance_agent.infrastructure.feishu_bitable_client import load_client_from_config

    client = load_client_from_config(load_feishu_config())
    recs = client.list_records(WORKER_INSURANCE_TABLE, page_size=500)
    print("总记录数: %d" % len(recs), flush=True)

    by_person = defaultdict(list)
    for r in recs:
        f = r.get("fields") or {}
        key = (str(f.get("姓名", "") or "").strip(), str(f.get("证件号码", "") or "").strip())
        if key[0] or key[1]:
            by_person[key].append(r)

    multi = {k: v for k, v in by_person.items() if len(v) > 1}
    print("存在重复的(姓名|证件号)组合: %d 组，涉及 %d 条" % (
        len(multi), sum(len(v) for v in multi.values())))

    to_delete = []
    keep_count = 0
    for key, items in multi.items():
        # 起始时间最新 → 保留；其余删除
        ordered = sorted(items, key=lambda r: _norm_date((r.get("fields") or {}).get("起始时间", "")))
        keep = ordered[-1]
        drop = ordered[:-1]
        keep_count += 1
        to_delete.extend(drop)

    print("将保留 %d 条，将删除 %d 条\n" % (keep_count, len(to_delete)))

    for r in to_delete[:15]:
        f = r["fields"]
        print("  删除 %s  %s %s  起始=%r 保单=%r" % (
            r["record_id"], f.get("姓名"), f.get("证件号码"),
            f.get("起始时间"), f.get("保单号")))
    if len(to_delete) > 15:
        print("  ... 其余 %d 条" % (len(to_delete) - 15))

    if not args.apply:
        print("\n[dry-run] 未执行删除。加 --apply 执行。")
        return
    if not to_delete:
        print("无需删除。")
        return

    # 备份
    backup = {
        "table_id": WORKER_INSURANCE_TABLE,
        "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": [{"record_id": r["record_id"], "fields": r["fields"]} for r in to_delete],
    }
    with open(BACKUP_PATH, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)
    print("\n已备份 %d 条 → %s" % (len(backup["items"]), BACKUP_PATH))

    deleted = client.batch_delete([r["record_id"] for r in to_delete], table_id=WORKER_INSURANCE_TABLE)
    print("已删除 %d 条" % deleted)

    recs2 = client.list_records(WORKER_INSURANCE_TABLE, page_size=500)
    by2 = defaultdict(int)
    for r in recs2:
        f = r.get("fields") or {}
        by2[(str(f.get("姓名", "") or "").strip(), str(f.get("证件号码", "") or "").strip())] += 1
    dup2 = {k: v for k, v in by2.items() if v > 1}
    print("\n清理后总记录数: %d，剩余重复组合: %d" % (len(recs2), len(dup2)))


if __name__ == "__main__":
    main()
