#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
保单人员去重：同名 + 同身份证号只保留「起止日期偏后」的一条。

用法：
    python tools/dedupe_insurance_personnel.py            # 预览（默认，不写库）
    python tools/dedupe_insurance_personnel.py --apply     # 实际执行（自动快照备份）

保留规则（排序键从大到小，取最大者保留）：
    1. start_date 靠后      ← 主规则（用户要求：保留起止日期偏后的一条）
    2. end_date   靠后
    3. status 有效优先      （正常/增保/替换 > 失效）
    4. policy_number 非空优先
    5. id 靠后
    特殊：日期为空的记录视为「最新」——它们是后补的变更批单（PDF 中未解析出日期），
          若按旧记录日期排序反而会保留过期条目。

字段合并（删除前先把被删条中「保留条为空」的字段补过来）：
    ✅ 参与合并：policy_number / company / insurance_company / job_title /
                  birth_date / source_file / id_type
    ❌ 不参与合并：start_date / end_date
                  ⚠️ 原因：保留条若为日期未解析出的后补批单，合并旧条的过期日期
                     会把在保人员误降为「失效」，导致覆盖率误判（11-03 实际踩过）。

安全约束：
    · 执行前自动快照（data/snapshots/app_before_dedup_*.db）
    · 默认 dry-run，必须显式 --apply 才写库
    · 执行后逐人校验「参保状态」是否翻转，若有翻转自动回滚
"""

import argparse
import collections
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "app.db"
)

# 视为「参保有效」的状态
EFFECTIVE_STATUS = ("正常", "增保", "替换")
# 参与字段合并的列（start_date / end_date 刻意排除）
MERGE_FIELDS = [
    "policy_number", "company", "insurance_company", "job_title",
    "birth_date", "source_file", "id_type",
]
# 保留条若为空且旧条也为空 → 不动
SNAPSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "snapshots"
)


def sort_key(rec):
    """保留条排序键：值越大越优先保留。"""
    status = (rec["status"] or "").strip()
    eff = 1 if status in EFFECTIVE_STATUS else 0
    # 空日期视为最新（后补变更批单）
    sd = (rec["start_date"] or "").strip() or "9999-12-31"
    ed = (rec["end_date"] or "").strip() or "9999-12-31"
    has_pol = 1 if (rec["policy_number"] or "").strip() else 0
    return (sd, ed, eff, has_pol, rec["id"])


def is_effective(rec, today):
    """该记录是否构成有效承保（用于校验）。"""
    status = (rec["status"] or "").strip()
    end = (rec["end_date"] or "").strip()
    return status != "失效" and (not end or end >= today)


def build_effective_map(conn, today):
    """人员 → 是否在保（多条记录取 OR）。"""
    m = {}
    cur = conn.execute(
        "SELECT name,id_number,status,end_date FROM insurance_personnel WHERE id_number!=''"
    )
    for r in cur:
        rec = {"status": r["status"], "end_date": r["end_date"]}
        k = (r["name"], r["id_number"])
        m[k] = m.get(k, False) or is_effective(rec, today)
    return m


def make_snapshot():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(SNAPSHOT_DIR, f"app_before_dedup_{ts}.db")
    src = sqlite3.connect(DB_PATH)
    dst_conn = sqlite3.connect(dst)
    with dst_conn:
        src.backup(dst_conn)   # SQLite 在线备份 API（WAL 模式安全）
    src.close()
    dst_conn.close()
    return dst


def main():
    ap = argparse.ArgumentParser(description="保单人员去重（同名同身份证保留日期偏后的一条）")
    ap.add_argument("--apply", action="store_true", help="实际执行（默认仅预览）")
    ap.add_argument("--db", default=DB_PATH, help="数据库路径")
    args = ap.parse_args()

    db = args.db
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    groups = cur.execute(
        """SELECT name, id_number FROM insurance_personnel
           WHERE id_number!='' GROUP BY name, id_number HAVING COUNT(*)>1"""
    ).fetchall()

    print(f"数据库: {db}")
    print(f"同名同身份证重复组: {len(groups)} 组")
    if not groups:
        print("无重复，无需处理。")
        conn.close()
        return

    to_delete = []
    merge_plan = []
    keep_stat = collections.Counter()
    del_stat = collections.Counter()
    merged_stat = collections.Counter()

    for g in groups:
        recs = [
            dict(r)
            for r in cur.execute(
                "SELECT * FROM insurance_personnel WHERE name=? AND id_number=?",
                (g["name"], g["id_number"]),
            )
        ]
        recs.sort(key=sort_key)
        keep, dels = recs[-1], recs[:-1]
        keep_stat[keep["status"]] += 1
        for d in dels:
            del_stat[d["status"]] += 1
        to_delete.extend(d["id"] for d in dels)

        upd = {}
        for f in MERGE_FIELDS:
            if not (keep[f] or "").strip():
                vals = [(d[f] or "").strip() for d in dels if (d[f] or "").strip()]
                if vals:
                    upd[f] = vals[0]
                    merged_stat[f] += 1
        if upd:
            merge_plan.append((keep["id"], upd))

    print(f"将删除记录: {len(to_delete)} 条")
    print("保留条状态分布:")
    for k, v in keep_stat.most_common():
        print(f"  {k or '(空)'}: {v} 组")
    print("被删记录状态分布:")
    for k, v in del_stat.most_common():
        print(f"  {k or '(空)'}: {v} 条")
    print(f"字段合并: {len(merge_plan)} 条记录")
    for k, v in merged_stat.most_common():
        print(f"  {k}: {v}")
    print(f"  (start_date / end_date 不参与合并 —— 避免把在保人员误降为失效)")

    if not args.apply:
        print("\n[预览模式] 未修改数据库。确认无误后加 --apply 执行。")
        conn.close()
        return

    # 执行前逐人快照参保状态
    before_map = build_effective_map(conn, today)

    snap = make_snapshot()
    print(f"\n✅ 已创建快照: {snap}")

    # 步骤1：删除重复记录（先删，避免与 UNIQUE(name,id_number,policy_number) 冲突）
    cur.executemany("DELETE FROM insurance_personnel WHERE id=?", [(i,) for i in to_delete])
    print(f"步骤1 删除: {cur.rowcount} 条")

    # 步骤2：字段合并
    for kid, upd in merge_plan:
        sets = ", ".join(f"{k}=?" for k in upd)
        cur.execute(f"UPDATE insurance_personnel SET {sets} WHERE id=?", [*upd.values(), kid])
    print(f"步骤2 字段合并: {len(merge_plan)} 条")
    conn.commit()

    # 步骤3：逐人校验参保状态是否翻转
    after_map = build_effective_map(conn, today)
    flip_off = [k for k in before_map if k in after_map and before_map[k] and not after_map[k]]
    lost = [k for k in before_map if k not in after_map]
    if flip_off or lost:
        print(f"\n❌ 校验失败：{len(flip_off)} 人参保状态异常翻转 / {len(lost)} 人丢失")
        for k in flip_off[:20]:
            print(f"    {k}")
        conn.close()
        shutil.copy2(snap, db)
        print(f"已自动回滚到快照: {snap}")
        sys.exit(1)

    print("\n✅ 校验通过：无人员丢失，无参保状态翻转")
    print(f"   总记录: {cur.execute('SELECT COUNT(*) FROM insurance_personnel').fetchone()[0]} 条")
    print(f"   重复组: {cur.execute('''SELECT COUNT(*) FROM (SELECT name,id_number FROM insurance_personnel "
                f"WHERE id_number!='' GROUP BY name,id_number HAVING COUNT(*)>1)''').fetchone()[0]} 组")
    print(f"   integrity: {cur.execute('PRAGMA integrity_check').fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()
