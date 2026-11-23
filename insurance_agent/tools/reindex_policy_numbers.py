# -*- coding: utf-8 -*-
"""按最新号段规则重算保单库索引（2026-11-23 新增）。

背景：
    8765 的保单库索引是**持久化**的 —— 提取规则（`_extract_policy_numbers`）修好之后，
    只对**新上传**的文件生效，历史已入库的 685 条记录不会自动重算。
    本脚本离线扫描 `policy_library/` 下的所有 PDF，用最新规则重算号段三元组
    （policy_number / main_policy_number / policy_type），并写回索引 JSON。

只改号段三字段，不动人员、日期、公司、险种等信息。

用法：
    python -m insurance_agent.tools.reindex_policy_numbers            # dry-run，出报告
    python -m insurance_agent.tools.reindex_policy_numbers --confirm  # 真正写盘（先备份）

2026-11-23 修复的规则：
    - 国寿「被保险人变动清单」：批单号标签是「业务凭证号」（2026G01...），
      主单号标签是「保险合同号」；旧逻辑既不认批单、也不认这两个标签。
    - 众安「保单号码」/「批单号码」：标签比「保单号」/「批单号」多一个「码」字，
      号段带 PS / PE 字母前缀。
"""
import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime

BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "policy_library",
)

# 号段新规则（与 metadata_extractor_node._extract_policy_numbers 保持一致）
PAT_BATCH = (
    r"批单号码[：:\s]*([A-Z0-9]{16,30})",
    r"批单号[：:\s]*([A-Z0-9]{16,30})",
    r"业务凭证号[：:\s]*([A-Z0-9]{16,30})",
)
PAT_MAIN = (
    r"保险单号[：:\s]*([A-Z0-9]{16,30})",
    r"保险合同号[：:\s]*([A-Z0-9]{16,30})",
    r"保单号码[：:\s]*([A-Z0-9]{16,30})",
    r"保单号[：:\s]*([A-Z0-9]{16,30})",
)
PAT_MAIN_ONLY = (
    r"保险单或凭证号次[\s\S]{0,30}?([A-Z0-9]{16,30})",
    r"凭证号次[\s\S]{0,30}?([A-Z0-9]{16,30})",
    r"汇交号[/／\s]*保险合同号[：:\s]*([A-Z0-9]{16,30})",
    r"保险合同号[：:\s]*([A-Z0-9]{16,30})",
    r"保险单号码?[：:\s]*([A-Z0-9]{16,30})",
    r"保单号码[：:\s]*([A-Z0-9]{16,30})",
    r"保单号[：:\s]*([A-Z0-9]{16,30})",
    r"保单流水号[\s\S]{0,30}?([A-Z0-9]{16,30})",
)


def extract_text(path):
    """提取 PDF 文本层（无文本层的扫描件返回空串）。"""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            return ""
    try:
        doc = pymupdf.open(path)
        text = "\n".join(p.get_text("text") for p in doc)
        doc.close()
        return text
    except Exception:
        return ""


def first_match(text, patterns):
    import re
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return ""


def has(text, kw):
    return kw in text


def recalc(text, file_name):
    """按新规则重算 (batch_no, main_no, policy_type)。"""
    import re
    # ---- 判定是否批单 ----
    is_batch = False
    if "批单" in file_name:
        is_batch = True
    if "BD" in file_name.upper():
        m_bd = re.search(r"(\d{16,30})_BD", file_name)
        if m_bd and m_bd.group(1)[0] == "8":
            is_batch = False
        else:
            is_batch = True
    if not is_batch:
        if has(text, "批单号") and has(text, "保险单号"):
            is_batch = True
        if has(text, "本次批改") or has(text, "批文"):
            is_batch = True
        if has(text, "批单生效日期"):
            is_batch = True
        if has(text, "批单号码"):
            is_batch = True
        if has(text, "业务凭证号") and has(text, "保险合同号"):
            is_batch = True

    if is_batch:
        batch_no = first_match(text, PAT_BATCH)
        main_no = first_match(text, PAT_MAIN)
        return batch_no, main_no, "批单"
    return "", first_match(text, PAT_MAIN_ONLY), "保单"


def load_index():
    main_p = os.path.join(BASE_DIR, "index_main.json")
    batch_p = os.path.join(BASE_DIR, "index_batch.json")
    with open(main_p, "r", encoding="utf-8") as f:
        main = json.load(f).get("records", [])
    with open(batch_p, "r", encoding="utf-8") as f:
        batch = json.load(f).get("records", [])
    return main_p, batch_p, main, batch


def save_index(main_p, batch_p, main, batch):
    with open(main_p, "w", encoding="utf-8") as f:
        json.dump({"records": main}, f, ensure_ascii=False, indent=2)
    with open(batch_p, "w", encoding="utf-8") as f:
        json.dump({"records": batch}, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="按新号段规则重算保单库索引")
    ap.add_argument("--confirm", action="store_true", help="真正写盘（默认 dry-run）")
    args = ap.parse_args()

    main_p, batch_p, main_recs, batch_recs = load_index()
    print(f"索引载入：main={len(main_recs)}  batch={len(batch_recs)}")
    print(f"目录：{BASE_DIR}")

    # file_name → (表名, 记录)
    all_recs = ([("main", r) for r in main_recs] +
                [("batch", r) for r in batch_recs])
    by_name = {r["file_name"]: (tbl, r) for tbl, r in all_recs}

    pdfs = sorted(f for f in os.listdir(BASE_DIR) if f.lower().endswith(".pdf"))
    print(f"PDF 文件：{len(pdfs)}\n")

    changes = []      # 可自动应用的变更
    conflicts = []    # 新旧号不一致 → 人工核对
    no_text = 0
    t0 = time.time()

    for i, fn in enumerate(pdfs, 1):
        if i % 100 == 0:
            print(f"  ... {i}/{len(pdfs)}  ({time.time() - t0:.0f}s)", flush=True)
        rec = by_name.get(fn)
        if not rec:
            continue
        tbl, r = rec
        text = extract_text(os.path.join(BASE_DIR, fn))
        if not text.strip():
            no_text += 1
            continue
        nb, nm, npt = recalc(text, fn)
        if not nb and not nm:
            continue

        opn = (r.get("policy_number") or "").strip()
        omn = (r.get("main_policy_number") or "").strip()
        opt = (r.get("policy_type") or "").strip()

        if npt == "批单":
            new_pn, new_mn = nb, nm
        else:
            new_pn, new_mn = nm, ""
        if not new_pn:
            continue

        # ---- 判定变更类型 ----
        if opn == new_pn and omn == new_mn and opt == npt:
            continue

        if not opn and new_pn:
            kind = "补空值"
        elif opt != "批单" and npt == "批单" and nb:
            kind = "类型纠正(保单→批单)"
        elif opn and new_pn != opn:
            # 判据（决定性）：旧值恰好等于新算出的「主保单号」
            #   → 说明旧值是主保单号被错填进 policy_number（2026-09-16 修过的
            #     利宝 BD 批单 bug 的历史遗留，代码修好了但索引没重算），
            #     新值才是真正的批单号。另有文件名佐证（批单号就在文件名里）。
            if new_mn and opn == new_mn:
                kind = "纠正历史错填(旧值=主单号)"
            elif new_pn in fn:
                kind = "纠正历史错填(文件名佐证)"
            else:
                kind = "号段冲突(需人工)"
                conflicts.append({
                    "file_name": fn, "table": tbl,
                    "old": {"pn": opn, "mn": omn, "pt": opt},
                    "new": {"pn": new_pn, "mn": new_mn, "pt": npt},
                })
                continue
        else:
            kind = "补充主单号/类型"

        changes.append({
            "file_name": fn, "table": tbl, "kind": kind,
            "old": {"pn": opn, "mn": omn, "pt": opt},
            "new": {"pn": new_pn, "mn": new_mn, "pt": npt},
        })

    print(f"\n扫描完成（{time.time() - t0:.0f}s，无文本层跳过 {no_text} 个）")
    print(f"可自动应用变更：{len(changes)}")
    print(f"需人工核对的号段冲突：{len(conflicts)}")

    from collections import Counter
    print("\n变更类型分布：")
    for k, v in Counter(c["kind"] for c in changes).most_common():
        print(f"  {k}: {v}")

    print("\n=== 变更明细（前 60 条）===")
    for c in changes[:60]:
        print(f"  [{c['kind']}] {c['file_name']}")
        print(f"      旧: pn={c['old']['pn']!r} mn={c['old']['mn']!r} pt={c['old']['pt']!r}")
        print(f"      新: pn={c['new']['pn']!r} mn={c['new']['mn']!r} pt={c['new']['pt']!r}")

    if conflicts:
        print("\n=== 号段冲突（不自动应用）===")
        for c in conflicts[:30]:
            print(f"  {c['file_name']}")
            print(f"      旧: pn={c['old']['pn']!r} mn={c['old']['mn']!r} pt={c['old']['pt']!r}")
            print(f"      新: pn={c['new']['pn']!r} mn={c['new']['mn']!r} pt={c['new']['pt']!r}")

    report = {"changes": changes, "conflicts": conflicts,
              "no_text": no_text, "scanned": len(pdfs)}
    with open(os.path.join(BASE_DIR, "_reindex_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已写入 {os.path.join(BASE_DIR, '_reindex_report.json')}")

    if not args.confirm:
        print("\n[dry-run] 未写盘。加 --confirm 执行实际更新。")
        return

    # ---------- 真正写盘 ----------
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(BASE_DIR, "backup")
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(main_p, os.path.join(bdir, f"index_main_{stamp}.json"))
    shutil.copy2(batch_p, os.path.join(bdir, f"index_batch_{stamp}.json"))
    print(f"\n已备份索引到 {bdir}/*_{stamp}.json")

    new_main = [dict(r) for r in main_recs]
    new_batch = [dict(r) for r in batch_recs]
    moved = 0
    for c in changes:
        tbl, r = by_name[c["file_name"]]
        src = new_main if tbl == "main" else new_batch
        dst = new_batch if c["new"]["pt"] == "批单" else new_main
        for i, rec in enumerate(src):
            if rec["file_name"] == c["file_name"]:
                rec["policy_number"] = c["new"]["pn"]
                rec["main_policy_number"] = c["new"]["mn"]
                rec["policy_type"] = c["new"]["pt"]
                if src is not dst:
                    src.pop(i)
                    dst.append(rec)
                    moved += 1
                break

    # ---- 去重：同一文件名在两表各登记一次（历史遗留）----
    # 保留号段更完整的那条（批单号 + 主单号都有 > 只有一个号），
    # 删除另一条。同名同文件的重复会让飞书端匹配到旧的那条。
    main_names = {r["file_name"] for r in new_main}
    dup_names = sorted(main_names & {r["file_name"] for r in new_batch})
    removed_dup = 0
    for fn in dup_names:
        rm = next(r for r in new_main if r["file_name"] == fn)
        rb = next(r for r in new_batch if r["file_name"] == fn)

        def _score(r):
            return (bool((r.get("policy_number") or "").strip()),
                    bool((r.get("main_policy_number") or "").strip()),
                    (r.get("policy_type") or "") == "批单")

        keep_batch = _score(rb) > _score(rm)
        print(f"  [去重] {fn[:50]} → 保留{'batch' if keep_batch else 'main'}记录")
        if keep_batch:
            new_main.remove(rm)
        else:
            new_batch.remove(rb)
        removed_dup += 1

    save_index(main_p, batch_p, new_main, new_batch)
    print(f"写盘完成：main={len(new_main)} batch={len(new_batch)}"
          f"（跨表迁移 {moved} 条，去重 {removed_dup} 条）")
    print("⚠️ 若 8765 服务仍在运行，调 POST /api/agent/reload 或重启服务让内存索引重新载入。")


if __name__ == "__main__":
    main()
