#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回填保单人员表里缺失的起止日期（针对扫描件保单）

背景（2026-11-13）：
    扫描件 PDF 没有文字层 → metadata_extractor 的保单号 / 保险期间
    全部取自 PyMuPDF 文字层 → 两者皆空。后果链：
      ① 清单表本身没有起止日期列 → 每个人的 start_date / end_date 为空
      ② policy_number 也为空 → 无法关联主保单回填 → 闭环断裂
    结果：整批人员入库后没有任何保险期间，无法判断是否在保。

本工具的做法：
    对每个「日期缺失」的来源文件，定位原始 PDF → OCR 首页版面元数据
    （保险单号 + 保险期间）→ 回填到该来源文件下所有日期缺失的记录。

安全约束：
    · 默认 dry-run，只打印计划，不写库
    · --apply 时先自动快照数据库，再逐条 UPDATE
    · 只改 start_date / end_date / policy_number，绝不动 name / id_number
      （避免触碰 (name, id_number) 唯一索引）
    · 只更新「日期为空」的记录，已有日期的一律不覆盖

用法：
    python tools/fix_missing_dates.py                       # dry-run：列出计划
    python tools/fix_missing_dates.py --apply               # 执行
    python tools/fix_missing_dates.py --apply --source-file "xxx.pdf"
    python tools/fix_missing_dates.py --no-ocr              # 不调 LLM，只列出缺失情况
"""

import argparse
import base64
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.join(ROOT, "data", "app.db")
POLICY_LIBRARY_DIR = os.path.join(ROOT, "policy_library")
POLICY_PDFS_DIR = os.path.join(ROOT, "data", "policy_pdfs")
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.expanduser("~")), "Downloads")


# ---------------------------------------------------------------- 定位 PDF

def _candidate_dirs() -> list[str]:
    return [POLICY_LIBRARY_DIR, POLICY_PDFS_DIR, DOWNLOADS_DIR]


def _index_paths() -> list[str]:
    """保单库索引里登记的原始 PDF 路径（文件名可能与 source_file 不同）"""
    paths = []
    for name in ("index_main.json", "index_batch.json"):
        idx = os.path.join(ROOT, "policy_library", name)
        if not os.path.exists(idx):
            continue
        try:
            with open(idx, encoding="utf-8") as fh:
                records = json.load(fh).get("records", [])
        except Exception:
            continue
        for rec in records:
            for key in ("stored_path", "file_path"):
                p = rec.get(key)
                if p and os.path.exists(p):
                    paths.append(p)
    return paths


def locate_pdf(source_file: str) -> str:
    """按 source_file 定位原始 PDF，返回路径或空串"""
    # 1) 直接按文件名在常见目录里找
    for d in _candidate_dirs():
        p = os.path.join(d, source_file)
        if os.path.exists(p):
            return p

    # 2) 去掉系统上传时追加的 "__xxxxxx" 后缀再找
    base = source_file
    if "__" in base:
        base = base.split("__")[0]
        for d in _candidate_dirs():
            for ext in (".pdf",):
                p = os.path.join(d, base + ext)
                if os.path.exists(p):
                    return p

    # 3) 保单库索引里的路径
    for p in _index_paths():
        if os.path.basename(p) == source_file or os.path.basename(p).split("__")[0] == base:
            return p
    return ""


# ---------------------------------------------------------------- OCR 元数据

def ocr_metadata(pdf_path: str) -> dict:
    """渲染首页并 OCR 出版面元数据（保险单号 / 保险期间）"""
    from dotenv import load_dotenv
    for env_file in (os.path.join(ROOT, "H-AGENT", ".env"), os.path.join(ROOT, ".env")):
        if os.path.exists(env_file):
            load_dotenv(env_file)

    import fitz
    from insurance_agent.infrastructure.llm.factory import create_minimax_llm_from_env
    from insurance_agent.extractors.ocr_extractor import OCRExtractor

    doc = fitz.open(pdf_path)
    try:
        pix = doc[0].get_pixmap(dpi=150)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()

    llm = create_minimax_llm_from_env()
    return OCRExtractor(llm_client=llm).extract_overall_metadata(
        page_images=[img_b64], max_pages=1
    )


# ---------------------------------------------------------------- 主流程

def collect_missing(db_path: str = DB_PATH, source_filter: str = "") -> dict:
    """找出日期缺失的记录，按 source_file 分组"""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT source_file, policy_number, company, insurance_company, "
            "       COUNT(*) AS cnt "
            "FROM insurance_personnel "
            "WHERE (start_date IS NULL OR start_date='') "
            "   OR (end_date IS NULL OR end_date='') "
        )
        params = []
        if source_filter:
            sql += " AND source_file = ?"
            params.append(source_filter)
        sql += " GROUP BY source_file ORDER BY cnt DESC"
        groups = [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()
    return {"groups": groups}


def build_plan(groups: list[dict], use_ocr: bool = True) -> list[dict]:
    """为每个来源文件生成修复计划"""
    plan = []
    for g in groups:
        src = g.get("source_file") or ""
        item = {
            "source_file": src,
            "affected": g["cnt"],
            "pdf": locate_pdf(src),
            "meta": {},
            "skip": "",
        }
        if not item["pdf"]:
            item["skip"] = "找不到原始 PDF"
            plan.append(item)
            continue
        if not use_ocr:
            item["skip"] = "--no-ocr：跳过 OCR"
            plan.append(item)
            continue
        try:
            meta = ocr_metadata(item["pdf"])
        except Exception as exc:
            item["skip"] = f"OCR 失败: {exc}"
            plan.append(item)
            continue

        item["meta"] = {
            "policy_number": meta.get("policy_number", ""),
            "overall_start_date": meta.get("overall_start_date", ""),
            "overall_end_date": meta.get("overall_end_date", ""),
            "total_persons": meta.get("total_persons", ""),
            "insurance_company": meta.get("insurance_company", ""),
        }
        if not (item["meta"]["overall_start_date"] and item["meta"]["overall_end_date"]):
            item["skip"] = "OCR 未读出保险期间"
        plan.append(item)
    return plan


def apply_plan(plan: list[dict], db_path: str = DB_PATH) -> dict:
    """执行回填（先快照，再逐条 UPDATE）"""
    from insurance_agent.tools.db_snapshot import backup_database

    snapshot = backup_database(tag="before_fix_missing_dates")
    print(f"[快照] 已创建数据库快照: {snapshot}\n")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    updated = 0
    skipped = 0
    details = []
    try:
        for item in plan:
            if item["skip"]:
                skipped += item["affected"]
                continue
            meta = item["meta"]
            src = item["source_file"]
            cur = con.execute(
                "UPDATE insurance_personnel "
                "   SET start_date = COALESCE(NULLIF(start_date,''), ?), "
                "       end_date   = COALESCE(NULLIF(end_date,''), ?), "
                "       policy_number = COALESCE(NULLIF(policy_number,''), ?) "
                " WHERE source_file = ? "
                "   AND ((start_date IS NULL OR start_date='') "
                "     OR (end_date IS NULL OR end_date=''))",
                (
                    meta["overall_start_date"],
                    meta["overall_end_date"],
                    meta["policy_number"],
                    src,
                ),
            )
            updated += cur.rowcount
            details.append(
                {
                    "source_file": src,
                    "affected": item["affected"],
                    "updated": cur.rowcount,
                    "period": f"{meta['overall_start_date']} ~ {meta['overall_end_date']}",
                    "policy_number": meta["policy_number"],
                }
            )
        con.commit()
    finally:
        con.close()

    return {"snapshot": snapshot, "updated": updated, "skipped": skipped, "details": details}


def main():
    ap = argparse.ArgumentParser(description="回填保单人员表缺失的起止日期（扫描件保单）")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认仅预览）")
    ap.add_argument("--source-file", default="", help="只处理指定的 source_file")
    ap.add_argument("--no-ocr", action="store_true", help="不调用 LLM，只列出缺失情况")
    args = ap.parse_args()

    info = collect_missing(source_filter=args.source_file)
    groups = info["groups"]

    total = sum(g["cnt"] for g in groups)
    print("=" * 78)
    print("保单人员表 —— 保险期间缺失统计")
    print("=" * 78)
    print(f"数据库: {DB_PATH}")
    print(f"日期缺失记录: {total} 条，涉及 {len(groups)} 个来源文件\n")

    if not groups:
        print("✅ 没有缺失记录，无需处理。")
        return

    plan = build_plan(groups, use_ocr=not args.no_ocr)

    print("-" * 78)
    print(f"{'来源文件':<52} {'条数':>6}  {'处理结果'}")
    print("-" * 78)
    for item in plan:
        src = (item["source_file"] or "(空)")[:50]
        if item["skip"]:
            result = f"⚠️ {item['skip']}"
        else:
            m = item["meta"]
            result = (
                f"✅ {m['overall_start_date']} ~ {m['overall_end_date']}"
                f" | {m['policy_number'] or '(无保单号)'}"
            )
        print(f"{src:<52} {item['affected']:>6}  {result}")

    print("-" * 78)

    if not args.apply:
        print("\n🔍 dry-run 模式（未写库）。加 --apply 执行实际回填。")
        return

    if args.no_ocr:
        print("\n❌ --no-ocr 与 --apply 不能同时使用（没有元数据可用于回填）。")
        return

    print("\n▶ 开始执行回填...\n")
    result = apply_plan(plan)
    print("=" * 78)
    print("执行结果")
    print("=" * 78)
    for d in result["details"]:
        print(
            f"  {d['source_file'][:46]:<46} "
            f"计划 {d['affected']:>4} → 实际更新 {d['updated']:>4}  "
            f"{d['period']}  {d['policy_number']}"
        )
    print(f"\n合计更新: {result['updated']} 条，跳过: {result['skipped']} 条")
    print(f"快照: {result['snapshot']}")


if __name__ == "__main__":
    main()
