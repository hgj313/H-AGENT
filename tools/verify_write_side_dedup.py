#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
写侧去重端到端验证（2026-11-05）

在**数据库副本**上验证新写侧规则，不触碰线上 data/app.db：
  1. 建唯一索引（init_db 迁移）
  2. 把库中全部记录当作"从 PDF 重新解析出来的数据"再喂一次 → 不得产生重复
  3. 同一批人改用**不同保单号**再喂一次 → 不得产生重复（本次缺陷的直接复现路径）
  4. 三种未参保口径的人数不得因写侧改动而变化

用法：
    python tools/verify_write_side_dedup.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SRC_DB = os.path.join(ROOT, "data", "app.db")


def backup_to(dst):
    """用 SQLite 在线备份 API 复制（WAL 模式安全，不能直接拷文件）"""
    src = sqlite3.connect(SRC_DB)
    dst_conn = sqlite3.connect(dst)
    with dst_conn:
        src.backup(dst_conn)
    src.close()
    dst_conn.close()


def stats(db_path, today):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) FROM insurance_personnel").fetchone()[0]
    dup = conn.execute(
        """SELECT COUNT(*) FROM (SELECT name, id_number FROM insurance_personnel
           WHERE id_number != '' GROUP BY name, id_number HAVING COUNT(*) > 1)"""
    ).fetchone()[0]
    # 口径 A：汇总链路 SQL（LEFT JOIN + status='正常'）
    a = conn.execute(
        """SELECT COUNT(DISTINCT pr.identification_number) FROM punch_records pr
           LEFT JOIN insurance_personnel ip
             ON pr.identification_number = ip.id_number AND ip.status = '正常'
           WHERE pr.punch_date = ? AND pr.identification_number IS NOT NULL
             AND pr.identification_number != '' AND pr.identification_number != 'undefined'
             AND ip.id_number IS NULL""",
        (today,),
    ).fetchone()[0]
    # 口径 B：实时链路 SQL（排除式 + end_date >= today）
    b = conn.execute(
        """SELECT COUNT(DISTINCT pr.identification_number) FROM punch_records pr
           WHERE pr.punch_date = ? AND pr.identification_number IS NOT NULL
             AND pr.identification_number != '' AND pr.identification_number != 'undefined'
             AND pr.identification_number NOT IN (
                 SELECT id_number FROM insurance_personnel
                 WHERE (status IS NULL OR status = '' OR status != '失效')
                   AND (end_date = '' OR end_date >= ?))""",
        (today, today),
    ).fetchone()[0]
    # 口径 C：Python 字典（界面 / 实时链路共用）
    active = {}
    for r in conn.execute("SELECT * FROM insurance_personnel"):
        if r["status"] in (None, "", "失效"):
            continue
        if r["end_date"] and r["end_date"] < today:
            continue
        active.setdefault(r["id_number"], []).append(dict(r))
    punch_ids = {r["identification_number"] for r in conn.execute(
        "SELECT DISTINCT identification_number FROM punch_records WHERE punch_date = ?",
        (today,))}
    c = len([i for i in punch_ids if i and i not in active])
    # 索引清单
    idx = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='insurance_personnel'")]
    conn.close()
    return {"total": total, "dup": dup, "A": a, "B": b, "C": c, "indexes": idx}


def load_persons(db_path, mutate_policy=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out = []
    for r in conn.execute("SELECT * FROM insurance_personnel"):
        p = dict(r)
        p["source_file"] = p.get("source_file") or ""
        if mutate_policy:
            p["policy_number"] = mutate_policy(p.get("policy_number") or "")
        out.append(p)
    conn.close()
    return out


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    tmpdir = tempfile.mkdtemp(prefix="dedup_verify_")
    work = os.path.join(tmpdir, "verify_app.db")
    backup_to(work)
    print(f"副本: {work}\n")

    before = stats(work, today)
    print("=== 改写前 ===")
    print(f"  保单人员总数: {before['total']}")
    print(f"  重复组: {before['dup']}")
    print(f"  今日未参保  口径A={before['A']}  口径B={before['B']}  口径C={before['C']}")
    print(f"  索引: {before['indexes']}")

    # 切换到副本库
    from insurance_agent.infrastructure import database as dbmod
    dbmod.DB_PATH = work
    dbmod.init_db()

    after_idx = stats(work, today)
    print("\n=== 建唯一索引后 ===")
    print(f"  索引: {after_idx['indexes']}")
    if "idx_person_name_id_uniq" not in after_idx["indexes"]:
        print("  ❌ 唯一索引未创建")
        sys.exit(1)
    print("  ✅ 唯一索引 idx_person_name_id_uniq 已建立")

    # 场景 1：全量重喂（保单号不变）
    persons = load_persons(work)
    r1 = dbmod.upsert_insurance_personnel_detailed(persons)
    s1 = stats(work, today)
    print("\n=== 场景 1：全量重喂（保单号不变）===")
    print(f"  新增={r1['added']} 替换={r1['updated']} 收敛={r1['collapsed']} 跳过={r1['skipped']}")
    print(f"  总数 {before['total']} → {s1['total']}   重复组 {s1['dup']}")
    print(f"  未参保 口径A={s1['A']} 口径B={s1['B']} 口径C={s1['C']}")

    # 场景 2：全量重喂，保单号全部改写（复现「同一份保单入库两次、保单号不同」）
    persons2 = load_persons(work, mutate_policy=lambda pn: f"DIFF_{pn}" if pn else "DIFF_NEW")
    r2 = dbmod.upsert_insurance_personnel_detailed(persons2)
    s2 = stats(work, today)
    print("\n=== 场景 2：全量重喂（保单号全部改写）===")
    print(f"  新增={r2['added']} 替换={r2['updated']} 收敛={r2['collapsed']} 跳过={r2['skipped']}")
    print(f"  总数 {before['total']} → {s2['total']}   重复组 {s2['dup']}")
    print(f"  未参保 口径A={s2['A']} 口径B={s2['B']} 口径C={s2['C']}")

    ok = True
    print("\n=== 结论 ===")
    if s1["dup"] != 0:
        print("  ❌ 场景 1 产生重复"); ok = False
    else:
        print("  ✅ 场景 1 未产生重复")
    if s2["dup"] != 0:
        print("  ❌ 场景 2 产生重复"); ok = False
    else:
        print("  ✅ 场景 2 未产生重复（保单号不同也不会新增）")
    if s2["total"] != before["total"]:
        print(f"  ⚠️ 总数变化 {before['total']} → {s2['total']}（应保持不变）")
    else:
        print(f"  ✅ 总数保持 {s2['total']} 条")
    for k in ("A", "B", "C"):
        if s2[k] != before[k]:
            print(f"  ❌ 口径{k} 未参保人数变化 {before[k]} → {s2[k]}"); ok = False
        else:
            print(f"  ✅ 口径{k} 未参保人数保持 {s2[k]} 人")

    shutil.rmtree(tmpdir, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
