"""验证 projects_limit：单项目测试模式

测试步骤：
1. 清除残留 last_daily_check
2. 临时替换经理数据为测试号
3. projects_limit=1：应只发 1 个项目（1 条短信）
4. projects_limit=0（force）：应发所有 6 个项目
5. 还原
"""
import sqlite3, json, urllib.request, pathlib

TEST_PHONE = "17723658267"
TEST_EMAIL = "1337382541@qq.com"
PUNCH_DATE = "2026-08-19"
DB_PATH = "data/app.db"
API = "http://127.0.0.1:8765"


def post(path):
    req = urllib.request.Request(API + path, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    # 1. 清残留
    cfg_path = pathlib.Path(".reminder_config.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.pop("last_daily_check", None)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已清除残留 last_daily_check")

    # 2. 替换
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT id, project_manager, manager_phone, manager_email
        FROM punch_records WHERE punch_date=? AND (manager_phone != '' OR manager_email != '')
    """, (PUNCH_DATE,))
    backup = cur.fetchall()
    cur.execute("""
        UPDATE punch_records SET manager_phone=?, manager_email=?
        WHERE punch_date=? AND (manager_phone != '' OR manager_email != '')
    """, (TEST_PHONE, TEST_EMAIL, PUNCH_DATE))
    con.commit()
    print(f"已临时替换 {cur.rowcount} 条")
    con.close()

    # 3. projects_limit=1
    print("\n=== 1) projects_limit=1 (预期: 只发 1 个项目 1 条短信) ===")
    r1 = post("/api/daily-check?skip_sync=true&projects_limit=1&force=true")
    print("skipped:", r1.get("skipped"))
    print("limited_projects:", r1.get("limited_projects"))
    print("email.message:", (r1.get("email") or {}).get("message"))
    print("sms.message:", (r1.get("sms") or {}).get("message"))
    print("sms.details count:", len((r1.get("sms") or {}).get("details") or []))

    # 4. projects_limit=0 (force)
    print("\n=== 2) projects_limit=0 (force) (预期: 发所有项目) ===")
    r2 = post("/api/daily-check?skip_sync=true&force=true")
    print("skipped:", r2.get("skipped"))
    print("limited_projects:", r2.get("limited_projects"))
    print("email.message:", (r2.get("email") or {}).get("message"))
    print("sms.message:", (r2.get("sms") or {}).get("message"))
    print("sms.details count:", len((r2.get("sms") or {}).get("details") or []))

    # 5. 还原
    print("\n=== 3) 还原 ===")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    for rec in backup:
        cur.execute("UPDATE punch_records SET project_manager=?, manager_phone=?, manager_email=? WHERE id=?",
                    (rec[1], rec[2], rec[3], rec[0]))
    con.commit()
    cur.execute("SELECT COUNT(*) FROM punch_records WHERE punch_date=? AND manager_phone=?",
                (PUNCH_DATE, TEST_PHONE))
    leak = cur.fetchone()[0]
    print(f"还原后 manager_phone 残留 {TEST_PHONE} 的记录数: {leak} (应为 0)")
    con.close()

    # 验证
    print("\n=== 验证清单 ===")
    n1 = len((r1.get("sms") or {}).get("details") or [])
    n2 = len((r2.get("sms") or {}).get("details") or [])
    ok1 = n1 == 1 and r1.get("limited_projects") and len(r1["limited_projects"]) == 1
    ok2 = n2 > 1 and not r2.get("limited_projects")
    ok3 = leak == 0
    print(f"[1] projects_limit=1: 短信 {n1} 条, 仅 1 个项目 → {'PASS' if ok1 else 'FAIL'}")
    print(f"[2] projects_limit=0: 短信 {n2} 条, 全项目   → {'PASS' if ok2 else 'FAIL'}")
    print(f"[3] 数据还原: {'PASS' if ok3 else 'FAIL'}")


if __name__ == "__main__":
    main()