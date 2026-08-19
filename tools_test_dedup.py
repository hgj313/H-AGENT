"""端到端验证 daily-check 今日去重

测试时把所有经理 phone/email 替换为 17723658267 / 1337382541@qq.com。
步骤：
1. 清除残留 last_daily_check
2. 临时替换经理数据为测试号
3. 第一次 daily-check：应真发
4. 第二次 daily-check（同日）：应跳过（skipped=true）
5. 第三次 daily-check（force=true）：应真发
6. 还原
"""
import sqlite3, json, urllib.request, urllib.error, pathlib

TEST_PHONE = "17723658267"
TEST_EMAIL = "1337382541@qq.com"
PUNCH_DATE = "2026-08-19"
DB_PATH = "data/app.db"
API = "http://127.0.0.1:8765"


def post(path):
    req = urllib.request.Request(API + path, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode("utf-8")[:600]}


def main():
    # 1. 清除残留 last_daily_check
    cfg_path = pathlib.Path(".reminder_config.json")
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg.pop("last_daily_check", None)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print("已清除残留 last_daily_check")

    # 2. 备份 + 临时替换
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
    print(f"已临时替换 {cur.rowcount} 条经理数据为测试号")
    con.close()

    # 3-5. 三次调用
    print("\n=== 1) 首次 /api/daily-check?skip_sync=true ===")
    r1 = post("/api/daily-check?skip_sync=true")
    print("skipped:", r1.get("skipped"))
    print("email.success:", (r1.get("email") or {}).get("success"))
    em1 = (r1.get("email") or {}).get("message", "")
    print("email.message:", em1[:80])
    print("sms.success:", (r1.get("sms") or {}).get("success"))

    print("\n=== 2) 第二次 /api/daily-check?skip_sync=true (预期: 跳过) ===")
    r2 = post("/api/daily-check?skip_sync=true")
    print("skipped:", r2.get("skipped"))
    print("skip_reason:", r2.get("skip_reason"))
    print("last_check.punch_date:", (r2.get("last_check") or {}).get("punch_date"))

    print("\n=== 3) 第三次 force=true (预期: 真发) ===")
    r3 = post("/api/daily-check?skip_sync=true&force=true")
    print("skipped:", r3.get("skipped"))
    print("email.success:", (r3.get("email") or {}).get("success"))
    em3 = (r3.get("email") or {}).get("message", "")
    print("email.message:", em3[:80])
    print("sms.success:", (r3.get("sms") or {}).get("success"))

    # 6. 还原
    print("\n=== 4) 还原 ===")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    for rec in backup:
        cur.execute("UPDATE punch_records SET project_manager=?, manager_phone=?, manager_email=? WHERE id=?",
                    (rec[1], rec[2], rec[3], rec[0]))
    con.commit()
    cur.execute("SELECT COUNT(*) FROM punch_records WHERE punch_date=? AND manager_phone=?",
                (PUNCH_DATE, TEST_PHONE))
    leak = cur.fetchone()[0]
    print(f"还原后 manager_phone 仍为 {TEST_PHONE} 的记录数: {leak} (应为 0)")
    con.close()

    # 验证
    print("\n=== 验证清单 ===")
    ok1 = (not r1.get("skipped")) and (r1.get("email") or {}).get("success")
    ok2 = r2.get("skipped") is True and "今日" in (r2.get("skip_reason") or "")
    ok3 = (not r3.get("skipped")) and (r3.get("email") or {}).get("success")
    ok4 = leak == 0
    print(f"[1] 首次发送: {'PASS' if ok1 else 'FAIL'}")
    print(f"[2] 同日跳过: {'PASS' if ok2 else 'FAIL'}")
    print(f"[3] force 重发: {'PASS' if ok3 else 'FAIL'}")
    print(f"[4] 数据还原: {'PASS' if ok4 else 'FAIL'}")


if __name__ == "__main__":
    main()