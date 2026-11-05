#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
写侧替换规则事实校准（一次性诊断脚本）

目的：为 upsert_insurance_personnel 的「同名同身份证 → 替换 or 不新增」规则
确定边界事实，避免规则拍脑袋导致：
  ① 误删跨保险公司的合法多保单
  ② 空日期覆盖真实日期导致在保人员被降级为失效

输入：归并前的快照 data/snapshots/app_before_dedup_*.db
输出：统计事实（不写库）
"""
import collections
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, "data", "snapshots")


def pick_snapshot():
    cands = [f for f in os.listdir(SNAP_DIR) if f.startswith("app_before_dedup_")]
    if not cands:
        sys.exit("找不到归并前快照")
    cands.sort()
    return os.path.join(SNAP_DIR, cands[-1])


def main():
    db_path = pick_snapshot()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    print(f"快照: {db_path}\n")

    groups = cur.execute(
        """SELECT name, id_number FROM insurance_personnel
           WHERE id_number!='' GROUP BY name, id_number HAVING COUNT(*)>1"""
    ).fetchall()
    print(f"重复组: {len(groups)} 组\n")

    stat = collections.Counter()
    diff_ins_company = []   # 同组内保险公司不同
    diff_company = []       # 同组内用工单位不同
    empty_vs_real = []      # 一条空日期、一条真实日期
    winner_loses_date = []  # 归并保留条缺日期、被删条有日期
    pol_variants = collections.Counter()

    for g in groups:
        recs = [dict(r) for r in cur.execute(
            "SELECT * FROM insurance_personnel WHERE name=? AND id_number=?",
            (g["name"], g["id_number"]))]

        # 复刻 tools/dedupe_insurance_personnel.py 的保留规则
        def sort_key(r):
            status = (r["status"] or "").strip()
            eff = 1 if status in ("正常", "增保", "替换") else 0
            sd = (r["start_date"] or "").strip() or "9999-12-31"
            ed = (r["end_date"] or "").strip() or "9999-12-31"
            has_pol = 1 if (r["policy_number"] or "").strip() else 0
            return (sd, ed, eff, has_pol, r["id"])

        recs.sort(key=sort_key)
        keep, dels = recs[-1], recs[:-1]

        ics = {(r["insurance_company"] or "").strip() for r in recs}
        cs = {(r["company"] or "").strip() for r in recs}
        if len(ics) > 1:
            diff_ins_company.append((g["name"], g["id_number"], sorted(ics)))
        if len(cs) > 1:
            diff_company.append((g["name"], g["id_number"], sorted(cs)))

        for r in recs:
            has_sd = bool((r["start_date"] or "").strip())
            has_ed = bool((r["end_date"] or "").strip())
            if not has_sd or not has_ed:
                empty_vs_real.append((g["name"], g["id_number"], r["id"],
                                     r["start_date"], r["end_date"], r["status"]))

        # 保留条缺日期、被删条有日期（合并后会不会丢日期）
        for d in dels:
            if not (keep["start_date"] or "").strip() and (d["start_date"] or "").strip():
                winner_loses_date.append(("start", g["name"], keep["id"], d["id"]))
            if not (keep["end_date"] or "").strip() and (d["end_date"] or "").strip():
                winner_loses_date.append(("end", g["name"], keep["id"], d["id"]))

        pols = [(r["policy_number"] or "").strip() for r in recs]
        pol_variants["|".join(sorted(pols))] += 1

    print("=== 事实 1：同组内保险公司是否不同 ===")
    print(f"  insurance_company 不同: {len(diff_ins_company)} 组")
    for x in diff_ins_company[:15]:
        print(f"    {x[0]} {x[1][:8]}*** {x[2]}")
    print(f"  company(用工单位) 不同: {len(diff_company)} 组")
    for x in diff_company[:15]:
        print(f"    {x[0]} {x[1][:8]}*** {x[2]}")

    print("\n=== 事实 2：日期为空 vs 真实日期 ===")
    print(f"  涉及记录: {len(empty_vs_real)} 条")
    for x in empty_vs_real[:20]:
        print(f"    {x[0]} id={x[2]} sd='{x[3]}' ed='{x[4]}' status={x[5]}")

    print("\n=== 事实 3：归并保留条是否会丢日期 ===")
    print(f"  {len(winner_loses_date)} 处")
    for x in winner_loses_date[:20]:
        print(f"    {x[0]} {x[1]} keep_id={x[2]} del_id={x[3]}")

    print("\n=== 事实 4：同组保单号组合（Top 12）===")
    for k, v in pol_variants.most_common(12):
        print(f"  {v:>4} 组  保单号集合 = {k!r}")

    conn.close()


if __name__ == "__main__":
    main()
