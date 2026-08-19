"""紧急恢复：把今日(2026-08-19)被测试号覆盖的真实经理数据还原

源数据：来自 session 早期输出（备份前的真实数据快照）。
按 (project_name, project_manager) 精确匹配回填 manager_phone / manager_email。
"""
import sqlite3

REAL_DATA = [
    ("上海中建三林滨江示范区景观工程", "杨红", "18983207321", "779385596@qq.com"),
    ("上海宸嘉徐汇区东安嘉佰道示范区景观工程", "张浩", "15856072805", "740406926@qq.com"),
    ("华南保利文海奕二期（文海围4#地）园林工程", "黄珍", "15320384882", "424492761@qq.com"),
    ("广州保利海珠区南泰路示范区", "赵宇", "18166441806", "295954887@qq.com"),
    ("广州保利玥玺湾1#9#楼盖上园林景观工程", "刘会洪", "18716323228", "624755523@qq.com"),
    ("广州华润白鹅潭项目二区核心南区景观工程", "刘���洪", "18716323228", "624755523@qq.com"),
    ("广州越秀琶洲南超级核心九米板示范区", "廖江红", "17318297411", "378898936@qq.com"),
    ("成都万华麓湖生态城C19组团景观总承包工程", "陈宇", "18306090989", "1213204378@qq.com"),
    ("成都华润青羊万家湾78亩示范区", "张文韬", "17823837679", "1505689105@qq.com"),
    ("成都金茂青羊区43.11亩示范区", "张晓刚", "13983895526", "15319578@qq.com"),
    ("成都金茂龙泉东洪片区62.62亩（东城金茂晓棠）大区园林景观工程", "胡俊杰", "18223315599", "402756227@qq.com"),
    ("无锡和居发展东亭金捷南地块大区景观绿化工程", "张晓刚", "13983895526", "15319578@qq.com"),
    ("杭州香港置地光环项目", "杨红", "18983207321", "779385596@qq.com"),
    ("深圳中海深湾玖序花园项目园建绿化及室外管网工程一标段（深超总项目）", "陈科翔", "13002321242", "1096464741@qq.com"),
    ("重庆观宸二期08-3地块景观工程", "尹祥", "19112021333", ""),
]

con = sqlite3.connect("data/app.db")
cur = con.cursor()

print("还原前:")
cur.execute("SELECT COUNT(*) FROM punch_records WHERE punch_date='2026-08-19' AND manager_phone='17723658267'")
print(f"  manager_phone=17723658267 的记录数: {cur.fetchone()[0]}")

total = 0
for proj, mgr, phone, email in REAL_DATA:
    cur.execute("""
        UPDATE punch_records
        SET manager_phone=?, manager_email=?
        WHERE punch_date='2026-08-19' AND project_name=? AND project_manager=? AND manager_phone='17723658267'
    """, (phone, email, proj, mgr))
    n = cur.rowcount
    print(f"  {proj} | {mgr}: 还原 {n} 条 -> {phone}/{email}")
    total += n

con.commit()

print("\n还原后:")
cur.execute("SELECT COUNT(*) FROM punch_records WHERE punch_date='2026-08-19' AND manager_phone='17723658267'")
print(f"  manager_phone=17723658267 的记录数: {cur.fetchone()[0]}（应为 0）")
cur.execute("SELECT COUNT(*) FROM punch_records WHERE punch_date='2026-08-19' AND manager_phone NOT IN ('17723658267', '')")
print(f"  manager_phone 为真实手机号的记录数: {cur.fetchone()[0]}（应为 376）")

# 抽查
cur.execute("SELECT project_name, project_manager, manager_phone, manager_email FROM punch_records WHERE punch_date='2026-08-19' AND project_name LIKE '%成都万华%' LIMIT 3")
print("\n抽查 成都万华:")
for r in cur.fetchall():
    print(" ", r)
con.close()