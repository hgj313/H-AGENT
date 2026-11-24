# -*- coding: utf-8 -*-
"""工人保险清单「状态」列全表归一

映射规则（按用户确认）：
    增保 → 正常
    减保 → 失效
    正常 / 失效 → 不动

⚠️ 精确匹配（==），不做 contains，避免误伤含「增保」的其他表述。

用法::

    python -m policy_analysis.normalize_status --dry-run   # 只列出将改的记录
    python -m policy_analysis.normalize_status --apply     # 备份 + 执行
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import WORKER_INSURANCE_TABLE, load_feishu_config

# 状态映射（精确匹配）
STATUS_MAPPING = {
    "增保": "正常",
    "减保": "失效",
}

BACKUP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "_backup_status_normalize.json",
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from insurance_agent.infrastructure.feishu_bitable_client import load_client_from_config

    client = load_client_from_config(load_feishu_config())
    recs = client.list_records(WORKER_INSURANCE_TABLE, page_size=500)

    to_update = []
    stat = {}
    for r in recs:
        f = r.get("fields") or {}
        cur = str(f.get("状态", "") or "").strip()
        stat[cur] = stat.get(cur, 0) + 1
        new = STATUS_MAPPING.get(cur)
        if new and new != cur:
            to_update.append({
                "record_id": r["record_id"],
                "fields": {"状态": new},
                "_before": cur,
                "_name": f.get("姓名", ""),
                "_id": f.get("证件号码", ""),
                "_policy": f.get("保单号", ""),
            })

    print("=== 归一前状态分布 ===")
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("  %-8r %d 条" % (k, v))
    print("\n待更新记录: %d 条" % len(to_update), flush=True)

    # 按目标值分组展示
    groups = {}
    for item in to_update:
        groups.setdefault(item["fields"]["状态"], []).append(item)
    for new_val, items in groups.items():
        print("\n--- %s ← %s（%d 条）---" % (new_val, "/".join(sorted(set(i["_before"] for i in items))), len(items)))
        for i in items[:10]:
            print("   %s  %s %s  保单=%s" % (i["record_id"], i["_name"], i["_id"], i["_policy"]))
        if len(items) > 10:
            print("   ... 其余 %d 条" % (len(items) - 10))

    if not args.apply:
        print("\n[dry-run] 未执行写入。加 --apply 执行。")
        return

    if not to_update:
        print("无需更新。")
        return

    # 1. 备份（记录 record_id + 原状态 + 关键字段）
    backup = {
        "table_id": WORKER_INSURANCE_TABLE,
        "created_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": [
            {
                "record_id": i["record_id"],
                "状态": i["_before"],
                "姓名": i["_name"],
                "证件号码": i["_id"],
                "保单号": i["_policy"],
            }
            for i in to_update
        ],
    }
    with open(BACKUP_PATH, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)
    print("\n已备份 %d 条 → %s" % (len(backup["items"]), BACKUP_PATH))

    # 2. 执行更新
    payload = [{"record_id": i["record_id"], "fields": i["fields"]} for i in to_update]
    updated = client.batch_update(payload, table_id=WORKER_INSURANCE_TABLE)
    print("已更新 %d 条" % len(updated))

    # 3. 验证
    recs2 = client.list_records(WORKER_INSURANCE_TABLE, page_size=500)
    stat2 = {}
    for r in recs2:
        cur = str((r.get("fields") or {}).get("状态", "") or "").strip()
        stat2[cur] = stat2.get(cur, 0) + 1
    print("\n=== 归一后状态分布 ===")
    for k, v in sorted(stat2.items(), key=lambda x: -x[1]):
        print("  %-8r %d 条" % (k, v))


if __name__ == "__main__":
    main()
