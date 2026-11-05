"""诊断：飞书推送的未参保人数 > 本地展示人数的根因（只读诊断，不改数据）。

对比三种口径：
  A. 汇总链路 SQL（LEFT JOIN ... IS NULL，GROUP BY 身份证+项目）
  B. 实时链路 SQL（同上，GROUP BY 身份证）
  C. Python 字典口径（coverage_check.get_active_insurance_by_id，实时/界面共用）
"""
import json
import sqlite3
import sys
from datetime import datetime

DB = r"C:\insurance-automation\data\app.db"
DEDUP = r"C:\insurance-automation\feishu_push_dedup.json"

today = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ---------- 口径 A：汇总链路（uninsured_summary.get_today_uninsured_persons） ----------
sql_a = """
SELECT pr.identification_number AS idn, pr.member_name AS nm, pr.project_name AS proj
FROM punch_records pr
LEFT JOIN insurance_personnel ip
       ON pr.identification_number = ip.id_number AND ip.status = '正常'
WHERE pr.punch_date = ?
  AND pr.identification_number IS NOT NULL AND pr.identification_number != ''
  AND pr.identification_number != 'undefined'
  AND ip.id_number IS NULL
GROUP BY pr.identification_number, pr.project_name
"""
a_rows = [dict(r) for r in conn.execute(sql_a, (today,))]

# ---------- 口径 B：实时链路 SQL（GROUP BY 身份证） ----------
sql_b = """
SELECT pr.identification_number AS idn, pr.member_name AS nm, pr.project_name AS proj
FROM punch_records pr
LEFT JOIN insurance_personnel ip
       ON pr.identification_number = ip.id_number
      AND (ip.status IS NULL OR ip.status = '' OR ip.status != '失效')
      AND (ip.end_date = '' OR ip.end_date >= ?)
WHERE pr.punch_date = ?
  AND pr.identification_number IS NOT NULL AND pr.identification_number != ''
  AND ip.id_number IS NULL
GROUP BY pr.identification_number
"""
b_rows = [dict(r) for r in conn.execute(sql_b, (today, today))]

# ---------- 口径 C：Python 字典（coverage_check / realtime 共用） ----------
conn.execute("UPDATE insurance_personnel SET status='失效' WHERE end_date != '' AND end_date < ?", (today,))
conn.commit()
active = {}
for r in conn.execute("SELECT * FROM insurance_personnel"):
    if r["status"] in (None, "", "失效"):
        continue
    if r["end_date"] and r["end_date"] < today:
        continue
    active.setdefault(r["id_number"], []).append(dict(r))

seen = {}
for r in conn.execute(
    "SELECT * FROM punch_records WHERE punch_date=? AND identification_number IS NOT NULL "
    "AND identification_number!=''", (today,)
):
    idn = r["identification_number"]
    if idn and idn not in seen:
        seen[idn] = dict(r)
c_rows = [
    {"idn": idn, "nm": rec["member_name"], "proj": rec["project_name"]}
    for idn, rec in seen.items()
    if idn not in active
]

# ---------- 飞书已推送 ----------
with open(DEDUP, encoding="utf-8") as f:
    dedup = json.load(f)
pushed = set(dedup.get(today, {}).keys())

set_a = {r["idn"] for r in a_rows}
set_b = {r["idn"] for r in b_rows}
set_c = {r["idn"] for r in c_rows}

print(f"日期: {today}")
print(f"  口径A 汇总SQL      : {len(a_rows):3d} 条 / {len(set_a):3d} 人")
print(f"  口径B 实时SQL      : {len(b_rows):3d} 条 / {len(set_b):3d} 人")
print(f"  口径C Python字典   : {len(c_rows):3d} 条 / {len(set_c):3d} 人   <== 界面/实时链路实际口径")
print(f"  飞书已推送         : {len(pushed):3d} 人")
print()

# 各人的保单记录明细
def detail(idn):
    rs = conn.execute(
        "SELECT id,name,status,start_date,end_date,policy_number,created_at,source_file "
        "FROM insurance_personnel WHERE id_number=? ORDER BY id", (idn,)
    ).fetchall()
    out = []
    for r in rs:
        out.append(
            f"{r['status']} {r['start_date']}~{r['end_date']} "
            f"pol={r['policy_number'] or '(空)'} created={r['created_at']}"
        )
    return out

extra = sorted(pushed - set_c)
print(f"=== 飞书有、界面无 的 {len(extra)} 人（多出来的）===")
for idn in extra:
    in_a = "A" if idn in set_a else "-"
    in_b = "B" if idn in set_b else "-"
    print(f"\n[{idn}] 汇总结算A={in_a} 实时SQL B={in_b}")
    for line in detail(idn):
        print("    ", line)

print(f"\n=== 界面有、飞书无 的 {len(set_c - pushed)} 人 ===")
for idn in sorted(set_c - pushed):
    print(f"  {idn} {detail(idn)}")

# 扇出检验：存在多条记录且含失效记录的人，是否被 SQL 误判
fanout = []
for idn, recs in active.items():
    pass
print("\n=== 反连接扇出检验（SQL 是否把「有正常记录」的人误判为未参保）===")
for idn in sorted(set_c | set_b | set_a):
    rs = conn.execute("SELECT status FROM insurance_personnel WHERE id_number=?", (idn,)).fetchall()
    if len(rs) > 1 and any(r["status"] == "正常" for r in rs):
        marks = []
        if idn in set_a:
            marks.append("A误判")
        if idn in set_b:
            marks.append("B误判")
        if idn not in set_c:
            marks.append("C误判")
        if marks:
            fanout.append((idn, len(rs), ",".join(marks)))
print(f"  被误判的人数: {len(fanout)}")
for x in fanout[:30]:
    print("   ", x)
conn.close()
