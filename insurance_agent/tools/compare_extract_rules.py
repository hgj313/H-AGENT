# -*- coding: utf-8 -*-
"""号段提取规则的新旧对比工具（2026-11-23 新增）。

用途：改了 `_extract_policy_numbers` 之后，用它对**保单库里全部 PDF** 做一次
新旧规则全量回归，确认「修复了多少、有没有引入退化」。

做法：从 `git show HEAD:<file>` 取出提交版本的模块，动态加载成独立模块，
与当前工作区版本逐文件对比三元组 (batch_no, main_no, policy_type)。

判定：
    - 结果一致          → 无变化
    - 修复（旧无新有）  → 新版多识别出了号
    - **退化（旧有新无）** → ⚠️ 必须为 0，否则说明改动破坏了既有识别

用法：
    python -m insurance_agent.tools.compare_extract_rules
    python -m insurance_agent.tools.compare_extract_rules --show 40
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node import (  # noqa: E402
    MetadataExtractorNode as NewM,
)
from insurance_agent.tools.reindex_policy_numbers import BASE_DIR, extract_text  # noqa: E402

REL = "insurance_agent/agents/invoice_recognition/nodes/metadata_extractor_node.py"


def load_head_module():
    """从 git HEAD 取出旧版模块并动态加载。"""
    try:
        src = subprocess.check_output(
            ["git", "-C", ROOT, "show", f"HEAD:{REL}"],
            text=True, encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"⚠️ 取 git HEAD 版本失败（{e}），无法对比。")
        return None
    fd, path = tempfile.mkstemp(suffix="_meta_node_head.py")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("old_meta_node_head", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MetadataExtractorNode


def main():
    ap = argparse.ArgumentParser(description="号段提取规则新旧全量对比")
    ap.add_argument("--show", type=int, default=40, help="打印前 N 条变化明细")
    args = ap.parse_args()

    OldM = load_head_module()
    if OldM is None:
        return 1

    pdfs = sorted(f for f in os.listdir(BASE_DIR) if f.lower().endswith(".pdf"))
    print(f"对比 {len(pdfs)} 个 PDF（基线 = git HEAD 版本）\n")

    same = 0
    changed = []
    lost = []      # 退化
    gained = []    # 修复

    for fn in pdfs:
        txt = extract_text(os.path.join(BASE_DIR, fn))
        if not txt.strip():
            continue
        old = OldM._extract_policy_numbers(txt, fn)
        new = NewM._extract_policy_numbers(txt, fn)
        if old == new:
            same += 1
            continue
        rec = {"file": fn, "old": old, "new": new}
        changed.append(rec)
        o_has = bool(old[0] or old[1])
        n_has = bool(new[0] or new[1])
        if o_has and not n_has:
            lost.append(rec)
        elif n_has and not o_has:
            gained.append(rec)

    print(f"结果一致: {same}")
    print(f"结果变化: {len(changed)}")
    print(f"  · 修复（旧无新有）: {len(gained)}")
    print(f"  · 退化（旧有新无）: {len(lost)}")
    print(f"  · 两者都有但取值不同: {len(changed) - len(gained) - len(lost)}")

    if lost:
        print("\n!!! 退化明细（必须为 0）!!!")
        for r in lost:
            print(f"  {r['file']}\n      旧 {r['old']}\n      新 {r['new']}")

    from collections import Counter

    def _kind(r):
        # 元组顺序是 (batch_no, main_no, policy_type)
        ob, om, ot = r["old"]
        nb, nm, nt = r["new"]
        if ot != nt:
            return f"类型 {ot or '空'}→{nt or '空'}"
        if ob != nb:
            return "批单号变化"
        return "主单号变化"

    print("\n=== 变化类型分布 ===")
    for k, v in Counter(_kind(r) for r in changed).most_common():
        print(f"  {k}: {v}")

    if args.show:
        print(f"\n=== 前 {args.show} 条变化明细 ===")
        for r in changed[:args.show]:
            ob, om, ot = r["old"]
            nb, nm, nt = r["new"]
            print(f"  {r['file'][:62]}")
            print(f"      旧: type={ot!r} batch={ob!r} main={om!r}")
            print(f"      新: type={nt!r} batch={nb!r} main={nm!r}")

    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
