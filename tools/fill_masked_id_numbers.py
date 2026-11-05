"""用人工填写的完整身份证号，补全保单人员表里的脱敏证件号。

背景（2026-10-28 张超误报事件）：
    平安养老/平安产险/申能财险的保单 PDF 里，证件号本身是脱敏的
    （如 34**************18），提取进库后仍是脱敏值。
    而 ERP 打卡推送的是完整 18 位身份证号，两边字符串永远不相等，
    导致明明有保险的人被判定为「打卡无正常保单」，并误发邮件/短信。

    解决方式：由人工根据保单原件补全身份证号（清单见
    data/待人工补全身份证号清单.csv），再用本脚本回写数据库。

用法：
    1. 打开 data/待人工补全身份证号清单.csv
    2. 在「完整身份证号(待填写)」列填入 18 位完整身份证号（未知的留空）
    3. 运行：python tools/fill_masked_id_numbers.py
       （先做 dry-run 预览，确认无误再加 --apply 实际写库）

安全：
    - 默认 dry-run，只打印将要改什么，不写库
    - --apply 才真正 UPDATE
    - 写库前自动备份 data/app.db
    - 校验：填入值必须是 18 位、末位数字或 X、且能被原脱敏号的可见位匹配上
"""

import argparse
import csv
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")
CSV_PATH = os.path.join(BASE_DIR, "data", "待人工补全身份证号清单.csv")

FULL_ID_RE = re.compile(r"^\d{17}[\dXx]$")


def visible_match(masked_id: str, full_id: str) -> bool:
    """完整号是否满足脱敏号的所有可见位。"""
    if len(masked_id) != len(full_id):
        return False
    for m, f in zip(masked_id, full_id):
        if m == "*":
            continue
        if m == "X" and f.upper() == "X":
            continue
        if m != f:
            return False
    return True


def read_filled_csv(csv_path: str) -> list[dict]:
    """读取已填写的 CSV，返回待补全的条目。"""
    if not os.path.exists(csv_path):
        print(f"[错误] 找不到清单文件：{csv_path}")
        sys.exit(1)

    items = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            full = (row.get("完整身份证号(待填写)") or "").strip().replace(" ", "")
            if not full:
                continue
            items.append({
                "name": (row.get("姓名") or "").strip(),
                "masked_id": (row.get("脱敏证件号") or "").strip(),
                "full_id": full,
                "policy_number": (row.get("保单号") or "").strip(),
                "insurance_company": (row.get("保险公司") or "").strip(),
            })
    return items


def validate(items: list[dict]) -> tuple[list[dict], list[tuple[dict, str]]]:
    """校验完整性，返回 (合法条目, 问题条目)。"""
    ok, problems = [], []
    for it in items:
        if not FULL_ID_RE.match(it["full_id"]):
            problems.append((it, "不是合法的18位身份证号"))
            continue
        if not visible_match(it["masked_id"], it["full_id"]):
            problems.append((it, "与脱敏号的可见位不符（可能填错或不是同一人）"))
            continue
        ok.append(it)
    return ok, problems


def apply_to_db(items: list[dict]) -> int:
    """把补全值写回数据库（同一 (姓名, 脱敏号) 可能有多条记录，全部更新）。

    ⚠️ 2026-11-05：insurance_personnel 已启用 partial UNIQUE INDEX
       (name, id_number) WHERE id_number != ''（一人一行）。
       若目标 (name, full_id) 已被库中另一条记录占用 → 直接 UPDATE 会撞约束。
       这里先做冲突检测，冲突项跳过并报告，绝不让整个批次挂掉。
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{DB_PATH}.bak.{stamp}_fill_masked_id"
    shutil.copy2(DB_PATH, backup)
    print(f"[备份] {backup}")

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        updated = 0
        conflicts = []
        for it in items:
            # 冲突检测：目标 (name, full_id) 是否已被另一条记录占用
            hit = cur.execute(
                """SELECT id, policy_number FROM insurance_personnel
                   WHERE name = ? AND id_number = ? LIMIT 1""",
                (it["name"], it["full_id"]),
            ).fetchone()
            if hit:
                conflicts.append((it, hit))
                continue
            cur.execute(
                """
                UPDATE insurance_personnel
                   SET id_number = ?
                 WHERE name = ? AND id_number = ?
                """,
                (it["full_id"], it["name"], it["masked_id"]),
            )
            updated += cur.rowcount
        conn.commit()
    finally:
        conn.close()

    if conflicts:
        print(f"\n⚠️ 跳过 {len(conflicts)} 条（目标完整证件号已被库中另一条记录占用）：")
        for it, hit in conflicts:
            print(f"  [{it['name']}] {it['masked_id']} -> {it['full_id']}"
                  f"  已占用记录 id={hit['id']} policy={hit['policy_number']!r}")
        print("  处理方式：先确认是否为同一人（若是，应先合并重复记录再补全）")
    return updated


def main():
    ap = argparse.ArgumentParser(description="补全保单人员表的脱敏身份证号")
    ap.add_argument("--csv", default=CSV_PATH, help="已填写的清单 CSV 路径")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认仅预览）")
    args = ap.parse_args()

    items = read_filled_csv(args.csv)
    if not items:
        print("[提示] 清单里没有已填写的完整身份证号，无需补全。")
        return

    ok, problems = validate(items)
    print(f"已填写 {len(items)} 条 | 校验通过 {len(ok)} 条 | 有问题 {len(problems)} 条")
    print()

    if problems:
        print("=== 校验不通过（已跳过）===")
        for it, reason in problems:
            print(f"  [{it['name']}] {it['masked_id']} -> {it['full_id']}  原因：{reason}")
        print()

    if not ok:
        print("[结束] 没有可写入的条目。")
        return

    print("=== 将要更新的记录 ===")
    for it in ok:
        print(f"  [{it['name']}] {it['masked_id']}  ->  {it['full_id']}   ({it['insurance_company']} {it['policy_number']})")

    if not args.apply:
        print()
        print("[预览模式] 未写库。确认无误后执行：")
        print("  python tools/fill_masked_id_numbers.py --apply")
        return

    print()
    n = apply_to_db(ok)
    print(f"[完成] 已更新 {n} 条记录。")
    print("提示：更新后需重启服务让新数据生效；历史打卡记录的对比结果会在下次巡检时自动修正。")


if __name__ == "__main__":
    main()
