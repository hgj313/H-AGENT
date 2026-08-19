"""验证：同一手机号同一天只收到一条 SMS（per-phone dedup）

测试流程：
1. 备份真实经理数据
2. 替换为测试手机号 (17723658267)
3. 第 1 次调用 daily-check: 期望成功发送 1 条 SMS
4. 第 2 次调用 daily-check (force=true): 期望发送 0 条 SMS（被 per-phone dedup 跳过）
5. 第 3 次调用 daily-check (force=true, project_filter=另一个项目):
   期望发送 1 条 SMS（因为是不同的手机号场景，但这里我们模拟同手机号换项目场景）

为简化测试，第 5 步仅验证「再次发同一手机号」一定被跳过。
"""
import sqlite3, json, urllib.request, urllib.error, urllib.parse, sys, pathlib

TEST_PHONE = "17723658267"
TEST_EMAIL = "1337382541@qq.com"
PROJECT_NAME = "成都万华麓湖生态城C19组团景观总承包工程"
PUNCH_DATE = "2026-08-19"
DB_PATH = "data/app.db"
API = "http://127.0.0.1:8765"
CONFIG_PATH = ".reminder_config.json"


def post(path):
    req = urllib.request.Request(API + path, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8')[:200]}"
    except Exception as e:
        return None, str(e)


def main():
    # 1. 清空 dedup 状态 + 备份配置
    cfg_path = pathlib.Path(CONFIG_PATH)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.pop("last_daily_check", None)
    cfg.pop("daily_sms_sent_today", None)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已清除 last_daily_check + daily_sms_sent_today")

    # 2. 备份并替换数据
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
    con.close()
    print(f"已替换 {len(backup)} 条经理数据为测试手机号")

    try:
        # 3. 第 1 次调用（带 force=true 清 dedup，期望：1 条 SMS 真正发送）
        qs = f"/api/daily-check?skip_sync=true&project_filter={urllib.parse.quote(PROJECT_NAME)}&force=true"
        print(f"\n=== 第 1 次调用（清 dedup 后）: {qs[:60]}... ===")
        result1, err = post(qs)
        if err:
            print("API ERROR:", err)
            return
        sms1 = (result1.get("sms") or {})
        print(f"短信 details: {len(sms1.get('details') or [])} 条")
        for d in sms1.get("details") or []:
            print(f"  target={d.get('target')} success={d.get('success')} skipped={d.get('skipped', False)} sent_count={d.get('sent_count', 0)}")

        # 4. 第 2 次调用（force=true 仍存在，应被 per-phone dedup 跳过）
        print(f"\n=== 第 2 次调用（force=true，应被跳过）: {qs[:60]}... ===")
        result2, err = post(qs)
        if err:
            print("API ERROR:", err)
            return
        sms2 = (result2.get("sms") or {})
        print(f"短信 details: {len(sms2.get('details') or [])} 条")
        for d in sms2.get("details") or []:
            print(f"  target={d.get('target')} success={d.get('success')} skipped={d.get('skipped', False)} sent_count={d.get('sent_count', 0)}")

        # 5. 第 3 次调用（同 phone, 同 project, force=true，应被跳过）
        print(f"\n=== 第 3 次调用（重复 force=true，应被跳过）: {qs[:60]}... ===")
        result3, err = post(qs)
        if err:
            print("API ERROR:", err)
            return
        sms3 = (result3.get("sms") or {})
        print(f"短信 details: {len(sms3.get('details') or [])} 条")
        for d in sms3.get("details") or []:
            print(f"  target={d.get('target')} success={d.get('success')} skipped={d.get('skipped', False)} sent_count={d.get('sent_count', 0)}")

        # 6. 验证清单
        print("\n=== 验证清单 ===")
        # 第 1 次：应有 1 条真实发送（success=True, sent_count>=1）
        d1 = (sms1.get("details") or [{}])[0]
        ok1 = d1.get("success") is True and (d1.get("sent_count") or 0) >= 1 and not d1.get("skipped")
        # 第 2 次：应被 per-phone dedup 跳过（skipped=True, sent_count=0 或 None）
        d2 = (sms2.get("details") or [{}])[0]
        ok2 = d2.get("skipped") is True and (d2.get("sent_count") or 0) == 0
        # 第 3 次：也应被跳过
        d3 = (sms3.get("details") or [{}])[0]
        ok3 = d3.get("skipped") is True and (d3.get("sent_count") or 0) == 0

        print(f"[1] 第 1 次调用：1 条 SMS 真正发送: {'PASS' if ok1 else 'FAIL'}")
        print(f"[2] 第 2 次调用：被 per-phone dedup 跳过: {'PASS' if ok2 else 'FAIL'}")
        print(f"[3] 第 3 次调用：仍被 per-phone dedup 跳过: {'PASS' if ok3 else 'FAIL'}")

        # 验证 dedup 状态已写入 config
        cfg_after = json.loads(cfg_path.read_text(encoding="utf-8"))
        sent_state = cfg_after.get("daily_sms_sent_today") or {}
        phones = sent_state.get("phones", [])
        ok4 = sent_state.get("punch_date") == PUNCH_DATE and TEST_PHONE in phones
        print(f"[4] daily_sms_sent_today 已持久化: {'PASS' if ok4 else 'FAIL'} ({sent_state})")

        # 验证总 SMS 发送量（应仅为 1 条）
        total_sent = (d1.get("sent_count") or 0) + (d2.get("sent_count") or 0) + (d3.get("sent_count") or 0)
        ok5 = total_sent == 1
        print(f"[5] 3 次调用总计仅发送 1 条 SMS（防 7 条重复）: {'PASS' if ok5 else 'FAIL'} (总计 {total_sent})")

        all_pass = ok1 and ok2 and ok3 and ok4 and ok5
        print(f"\n总评: {'✅ 全部通过 - per-phone dedup 已生效' if all_pass else '❌ 存在失败'}")
    finally:
        # 还原真实经理数据
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
        # 清空本次测试产生的 dedup 状态
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg.pop("daily_sms_sent_today", None)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已还原 {len(backup)} 条经理数据；残留 {TEST_PHONE}: {leak}")


if __name__ == "__main__":
    main()