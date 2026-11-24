"""诊断：飞书多维表格「打卡无正常保险人员」记录缺列问题

背景
----
保险AI助手把「今日打卡无正常保单」的人员推送到飞书多维表格（自动化 webhook）。
用户反馈同步过去的记录**缺少「项目」等信息**。

排查结论（见 2026-11-24 工作日志）
----------------------------------
本脚本用于把「本地有没有值」和「飞书有没有收到」这两件事**彻底分离**，
避免在飞书端盲猜。

三层判定
--------
1. **本地数据层**：`punch_records` 表里 `project_name` 等字段是否为空
   → 若本地就空，则问题在 ERP 数据源 / 入库环节，与飞书无关。
2. **推送载荷层**：实际 POST 出去的 JSON body 里有没有这些字段、值是什么
   → 若 body 里有值，则本地与传输层都正常。
3. **飞书映射层**：body 里有值但表格列为空 → 只能是飞书端的问题
   → 自动化流程「输出设置」的 JSON Schema 未声明该字段，
     下游「添加记录」节点无法引用（schema 不可修改，需重新生成）。

用法
----
```bash
# 1) 本地数据体检（今日未参保人员的字段空值统计）
.venv/Scripts/python.exe tools/diag_feishu_fields.py --local

# 2) 发一条带全部字段的探测记录，并打印完整请求体
.venv/Scripts/python.exe tools/diag_feishu_fields.py --probe

# 3) 只打印将要发送的请求体（不发网络请求），用于比对飞书 schema
.venv/Scripts/python.exe tools/diag_feishu_fields.py --show-payload

# 4) 指定日期
.venv/Scripts/python.exe tools/diag_feishu_fields.py --local --date 2026-11-23
```

⚠️ `--probe` 会真的往飞书表格里写一条测试记录，请到飞书里删掉。
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from insurance_agent.infrastructure import database as db  # noqa: E402

# payload key → punch_records 列名
PAYLOAD_TO_COLUMN = {
    "name": "member_name",
    "id_number": "identification_number",
    "project_name": "project_name",
    "team_name": "team_name",
    "supplier_name": "supplier_name",
    "category_name": "category_name",
    "project_manager": "project_manager",
    "manager_phone": "manager_phone",
    "manager_email": "manager_email",
    "punch_time": "punch_time",
    "punch_date": "punch_date",
}

# 飞书多维表格里通常关心的列（缺失时优先排查）
KEY_COLUMNS = ["project_name", "team_name", "supplier_name",
               "category_name", "project_manager", "manager_phone", "manager_email"]


def _load_webhook_config():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".feishu_webhook.json")
    if not os.path.exists(path):
        print(f"!! 未找到配置文件: {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_probe_payload(punch_date: str = None) -> dict:
    """构造一条带全部字段的探测记录（值均为可识别的自检标记）。"""
    punch_date = punch_date or datetime.now().strftime("%Y-%m-%d")
    stamp = datetime.now().strftime("%Y/%m/%d %H:%M")
    return {
        "name": "【字段自检】请删除本行",
        "id_number": f"SELFCHECK{uuid.uuid4().hex[:8].upper()}",
        "project_name": "【自检】项目名称",
        "team_name": "【自检】班组",
        "supplier_name": "【自检】劳务公司",
        "category_name": "【自检】劳务分类",
        "project_manager": "【自检】项目经理",
        "manager_phone": "13900000000",
        "manager_email": "selfcheck@example.com",
        "punch_time": stamp,
        "punch_date": punch_date,
    }


def cmd_local(punch_date: str) -> int:
    """第一层：本地数据体检。"""
    print("=" * 72)
    print(f"【第一层】本地数据体检 — punch_records @ {punch_date}")
    print("=" * 72)

    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pr.member_name, pr.identification_number, pr.project_name,
                   pr.team_name, pr.supplier_name, pr.category_name,
                   pr.project_manager, pr.manager_phone, pr.manager_email,
                   MIN(pr.punch_time) AS first_punch
            FROM punch_records pr
            LEFT JOIN insurance_personnel ip
                ON pr.identification_number = ip.id_number
               AND ip.status = '正常'
            WHERE pr.punch_date = ?
              AND pr.identification_number IS NOT NULL
              AND pr.identification_number != ''
              AND pr.identification_number != 'undefined'
              AND ip.id_number IS NULL
            GROUP BY pr.identification_number, pr.project_name
            """,
            (punch_date,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    total = len(rows)
    print(f"今日未参保人员: {total} 人")
    if total == 0:
        print("\n提示: 若人数为 0，可能是当日尚无打卡数据，"
              "或 punch_records 已被 daily_cleanup 清理（默认只保留当天）。")
        return 0

    print("\n--- 字段空值统计（推送口径）---")
    # payload key → 在 SELECT 结果中的列下标（与 PAYLOAD_TO_COLUMN 的取值顺序一致）
    col_index = {
        "name": 0,
        "id_number": 1,
        "project_name": 2,
        "team_name": 3,
        "supplier_name": 4,
        "category_name": 5,
        "project_manager": 6,
        "manager_phone": 7,
        "manager_email": 8,
        "punch_time": 9,
        "punch_date": 9,  # 派生自 punch_time
    }
    for pk in PAYLOAD_TO_COLUMN:
        idx = col_index[pk]
        empty = sum(1 for r in rows if not (r[idx] or "").strip())
        flag = "  <== 关注" if pk in KEY_COLUMNS and empty else ""
        print(f"  {pk:<18} 空: {empty}/{total}{flag}")

    print("\n--- 明细（前 20 人）---")
    for r in rows[:20]:
        print(f"  {r[0] or '':<10} 项目={str(r[2] or '')[:32]:<34} "
              f"班组={str(r[3] or ''):<14} 劳务={str(r[4] or '')[:18]:<20} 分类={r[5] or ''}")

    print("\n" + "=" * 72)
    print("判定：")
    print("  · 上表「项目/班组/劳务公司」等若空值=0  →  本地数据完整，问题在飞书端映射")
    print("  · 若空值>0  →  本地就缺值，需先查 ERP 数据源 / 入库环节")
    print("=" * 72)
    return 0


def cmd_show_payload() -> int:
    """只打印请求体，不发网络请求。"""
    payload = build_probe_payload()
    print("=" * 72)
    print("【第二层】将要发送的请求体（未发送）")
    print("=" * 72)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n字段数: {len(payload)}")
    print("\n用途：与飞书自动化流程「输出设置」的 JSON Schema 逐项比对。")
    print("Schema 里没有的字段 → 下游「添加记录」节点无法引用 → 表格该列必然为空。")
    return 0


def cmd_probe(punch_date: str = None) -> int:
    """发一条探测记录并打印完整响应。"""
    cfg = _load_webhook_config()
    if not cfg:
        return 1
    if not cfg.get("enabled"):
        print("!! .feishu_webhook.json 中 enabled=false，探测已跳过")
        return 1

    import requests

    payload = build_probe_payload(punch_date)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {cfg.get('bearer_token', '')}",
        "Content-Type": "application/json; charset=utf-8",
        "Client-Token": uuid.uuid4().hex,
    }

    print("=" * 72)
    print("【第二层】发送探测记录")
    print("=" * 72)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n请求体字节数: {len(body)}  字段数: {len(payload)}")

    try:
        resp = requests.post(cfg["webhook_url"], data=body, headers=headers, timeout=12)
    except Exception as e:  # noqa: BLE001
        print(f"!! 请求失败: {e}")
        return 1

    print(f"HTTP {resp.status_code}")
    print(f"响应: {resp.text[:400]}")
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        data = {}
    if data.get("code") == 0:
        print("\n✅ webhook 接收成功（code=0）")
        print("   → 触发器已接受本请求。若表格对应列仍为空，")
        print("     则问题在飞书自动化流程的「输出设置」schema / 「添加记录」映射，")
        print("     而非本地数据或网络传输。")
        print("\n请到飞书表格核对：'【字段自检】请删除本行' 这一行，")
        print("  哪些列有值、哪些列是空的 —— 空列即 schema 未声明的字段。")
    else:
        print("\n❌ 业务错误，请对照飞书官方错误码表排查")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="飞书多维表格字段缺失诊断")
    ap.add_argument("--local", action="store_true", help="本地数据体检")
    ap.add_argument("--probe", action="store_true", help="发送探测记录（会写入飞书）")
    ap.add_argument("--show-payload", action="store_true", help="仅打印请求体")
    ap.add_argument("--date", default=None, help="打卡日期 YYYY-MM-DD，默认今天")
    args = ap.parse_args()

    if not (args.local or args.probe or args.show_payload):
        ap.print_help()
        return 0

    punch_date = args.date or datetime.now().strftime("%Y-%m-%d")
    if args.local:
        cmd_local(punch_date)
    if args.show_payload:
        cmd_show_payload()
    if args.probe:
        cmd_probe(punch_date)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
