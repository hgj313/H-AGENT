"""安全测试：流程 A 路由 + 流程 B 邮件

测试要求：
- 只允许发送至 17723658267 / 1337382541@qq.com（绝不给真实经理发送）
- 流程 B：触发到期提醒，仅发邮件到固定收件人（不动测试数据）

流程：
1. 备份 punch_records 中今日所有 manager 字段
2. 把今日 punch_records 的 manager_phone/manager_email 临时替换为测试号
3. 调用 /api/daily-check?skip_sync=true（流程 A 真发）
4. 立即还原 manager 字段
5. 调用 /api/reminder/check-expiry（流程 B 真发邮件到固定收件人）
6. 打印每次发往的目标和结果
"""
import sqlite3, json, sys, time, urllib.request, urllib.parse

TEST_PHONE = "17723658267"
TEST_EMAIL = "1337382541@qq.com"
PUNCH_DATE = "2026-08-19"
DB_PATH = "data/app.db"
API = "http://127.0.0.1:8765"


def post(path, body=None):
    url = API + path
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode("utf-8")[:600]}


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # 1. 备份原始 manager 字段
    print("=== 1) 备份原始经理数据 ===")
    cur.execute("""
        SELECT id, project_name, project_manager, manager_phone, manager_email
        FROM punch_records
        WHERE punch_date=? AND (manager_phone != '' OR manager_email != '')
    """, (PUNCH_DATE,))
    backup = cur.fetchall()
    print(f"备份 {len(backup)} 条经理数据")
    distinct_real_phones = sorted({r[3] for r in backup if r[3]})
    print(f"真实经理手机(用于事后确认未发送): {distinct_real_phones}")

    # 2. 临时替换为测试号
    print("\n=== 2) 临时替换 manager_phone/email 为测试号 ===")
    cur.execute("""
        UPDATE punch_records
        SET manager_phone=?, manager_email=?
        WHERE punch_date=? AND (manager_phone != '' OR manager_email != '')
    """, (TEST_PHONE, TEST_EMAIL, PUNCH_DATE))
    con.commit()
    updated = cur.rowcount
    print(f"已临时替换 {updated} 条记录的经理手机/邮箱为 {TEST_PHONE} / {TEST_EMAIL}")
    print(f"(保留 project_manager 真实姓名以保持项目分组正确)")

    sms_log = []  # 记录真实发送结果供事后核查

    try:
        # 3. 触发流程 A
        print("\n=== 3) 触发流程 A: POST /api/daily-check?skip_sync=true ===")
        # 加 skip_sync 避免再次同步覆盖回真实经理
        result = post(f"/api/daily-check?skip_sync=true")
        print(json.dumps(result, ensure_ascii=False, indent=2)[:2200])
        sms_log.append(("flowA_daily_check", result))
    finally:
        # 4. 立即还原
        print("\n=== 4) 还原原始经理数据 ===")
        for rec in backup:
            cur.execute("""
                UPDATE punch_records
                SET project_manager=?, manager_phone=?, manager_email=?
                WHERE id=?
            """, (rec[2], rec[3], rec[4], rec[0]))
        con.commit()
        print(f"已还原 {len(backup)} 条经理数据")

        # 验证还原成功
        cur.execute("""
            SELECT COUNT(*) FROM punch_records
            WHERE punch_date=? AND manager_phone NOT IN (?, '')
        """, (PUNCH_DATE, TEST_PHONE))
        cnt = cur.fetchone()[0]
        print(f"还原后 manager_phone 不为 {TEST_PHONE} 的记录数: {cnt}（预期：{len(distinct_real_phones)} 个真实手机号的记录数）")
    con.close()

    # 5. 触发流程 B（不动测试数据，固定收件人本就是测试邮箱）
    print("\n=== 5) 触发流程 B: POST /api/reminder/check-expiry ===")
    result_b = post("/api/reminder/check-expiry")
    print(json.dumps(result_b, ensure_ascii=False, indent=2)[:1500])
    sms_log.append(("flowB_expiry", result_b))

    # 6. 结果汇总
    print("\n=== 6) 验证清单 ===")
    flowA = sms_log[0][1]
    flowB = sms_log[1][1]

    # 流程 A 检查：固定手机号 18203050571 不应被发送
    if isinstance(flowA, dict) and "sms" in flowA:
        sms_details = flowA.get("sms", {}).get("details", [])
        hit_fixed_aggregate = any(
            d.get("target") and "18203050571" in str(d.get("target"))
            for d in sms_details
        )
        hit_test_only = all(
            TEST_PHONE in str(d.get("target") or "")
            for d in sms_details
        )
        print(f"[流程A] 固定手机号 18203050571 是否仍被发送? {hit_fixed_aggregate}（预期：False）")
        print(f"[流程A] 所有短信是否只发给 {TEST_PHONE}? {hit_test_only}（预期：True）")
    else:
        print(f"[流程A] 异常: {flowA}")

    # 流程 B 检查：结果中无 sms 字段
    print(f"[流程B] result 是否含 sms 字段? {'sms' in flowB}（预期：False）")
    print(f"[流程B] email 发送目标: {flowB.get('email', {}).get('message', '?')[:200]}")

    # 流程 A 检查：真实经理手机号不应出现在 details 中
    if isinstance(flowA, dict) and "sms" in flowA:
        sms_details = flowA.get("sms", {}).get("details", [])
        real_leak = [
            d for d in sms_details
            if any(phone in str(d.get("target") or "") for phone in distinct_real_phones)
        ]
        print(f"[流程A] 真实经理手机号被发送的条数: {len(real_leak)}（预期：0）")


if __name__ == "__main__":
    main()