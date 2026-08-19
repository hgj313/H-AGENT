"""精确按项目名测试：成都万华麓湖生态城C19组团景观总承包工程

收件人：手机 17723658267 / 邮箱 1337382541@qq.com
使用 try/finally 确保即使 API 报错也能还原经理数据。
"""
import sqlite3, json, urllib.request, urllib.parse, pathlib, sys

TEST_PHONE = "17723658267"
TEST_EMAIL = "1337382541@qq.com"
PROJECT_NAME = "成都万华麓湖生态城C19组团景观总承包工程"
PUNCH_DATE = "2026-08-19"
DB_PATH = "data/app.db"
API = "http://127.0.0.1:8765"


def post(path):
    req = urllib.request.Request(API + path, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8')[:200]}"
    except Exception as e:
        return None, str(e)


def restore(backup):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    for rec in backup:
        cur.execute("UPDATE punch_records SET project_manager=?, manager_phone=?, manager_email=? WHERE id=?",
                    (rec[1], rec[2], rec[3], rec[0]))
    con.commit()
    cur.execute("SELECT COUNT(*) FROM punch_records WHERE punch_date=? AND manager_phone=?",
                (PUNCH_DATE, TEST_PHONE))
    leak = cur.fetchone()[0]
    con.close()
    return leak


def main():
    # 1. 清残留
    cfg_path = pathlib.Path(".reminder_config.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.pop("last_daily_check", None)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已清除残留 last_daily_check")

    # 2. 备份
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT id, project_manager, manager_phone, manager_email
        FROM punch_records WHERE punch_date=? AND (manager_phone != '' OR manager_email != '')
    """, (PUNCH_DATE,))
    backup = cur.fetchall()
    con.close()

    # 3. 替换
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        UPDATE punch_records SET manager_phone=?, manager_email=?
        WHERE punch_date=? AND (manager_phone != '' OR manager_email != '')
    """, (TEST_PHONE, TEST_EMAIL, PUNCH_DATE))
    con.commit()
    print(f"已临时替换 {cur.rowcount} 条经理数据为 {TEST_PHONE} / {TEST_EMAIL}")
    con.close()

    result = None
    err = None
    try:
        # 4. 调用
        qs = "/api/daily-check?skip_sync=true&project_filter=" + urllib.parse.quote(PROJECT_NAME) + "&force=true"
        print(f"\n=== POST {qs[:60]}... ===")
        result, err = post(qs)
        if err:
            print("API ERROR:", err)
        else:
            print("=== 完整响应 ===")
            print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
    finally:
        # 5. 还原（无论 API 是否成功都执行）
        leak = restore(backup)
        print(f"\n已还原 {len(backup)} 条经理数据；残留 {TEST_PHONE}: {leak} (应为 0)")

    if not result:
        return

    # 6. 验证清单
    print("\n=== 验证清单 ===")
    sms_details = (result.get("sms") or {}).get("details") or []
    email_details = (result.get("email") or {}).get("details") or []
    limited = result.get("limited_projects") or []
    print(f"短信 details 条数: {len(sms_details)}（预期 1）")
    if sms_details:
        d = sms_details[0]
        print(f"短信 target: {d.get('target')}")
        print(f"短信 success: {d.get('success')}  sent_count: {d.get('sent_count')}  message: {d.get('message')}")
    email_targets = [d.get("target") for d in email_details]
    print(f"邮件 targets: {email_targets}")
    print(f"limited_projects: {limited}")

    ok1 = len(sms_details) == 1 and TEST_PHONE in (sms_details[0].get("target") or "")
    # 注意：send_sms 返回值不含 messages 字段（仅 success/message/sent_count），
    # 短信内容正确性需通过上游 build_sms_messages + 路由限制间接证明：
    # - limited_projects 仅含 1 个项目（成都万华）→ send_sms 只收到了 1 条 messages
    # - send_sms 返回 success=True + sent_count>=1 → 已送达
    ok2 = (
        bool(sms_details)
        and sms_details[0].get("success") is True
        and (sms_details[0].get("sent_count") or 0) >= 1
        and "陈宇" in (sms_details[0].get("target") or "")  # 项目经理姓名也匹配（陈宇=成都万华经理）
    )
    ok3 = any("1337382541@qq.com" in t for t in email_targets)
    ok4 = "成都万华" in str(limited) and len(limited) == 1
    print(f"\n[1] 短信仅 1 条 + 到 {TEST_PHONE}: {'PASS' if ok1 else 'FAIL'}")
    print(f"[2] 短信发送成功且 sent_count≥1（路由到 陈宇）: {'PASS' if ok2 else 'FAIL'}")
    print(f"[3] 邮件含 {TEST_EMAIL}: {'PASS' if ok3 else 'FAIL'}")
    print(f"[4] limited_projects 仅 1 个项目（成都万华）: {'PASS' if ok4 else 'FAIL'}")


if __name__ == "__main__":
    main()