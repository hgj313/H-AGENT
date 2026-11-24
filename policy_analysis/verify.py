# -*- coding: utf-8 -*-
"""端到端验证工具

对「保险单」表里「保险单号为空」的待处理记录，跑完整链路（下载→AI分析→回写）。

用法::

    # dry-run：只分析不写回，打印结果
    python -m policy_analysis.verify --dry-run

    # 实际写回（处理所有待处理记录）
    python -m policy_analysis.verify --apply
"""

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import (
    INSURANCE_POLICY_TABLE, load_feishu_config, create_llm_client,
)
from .ai_analyzer import AIAnalyzer
from .writer import PolicyWriter


def _download(client, att: dict) -> str:
    import requests
    headers = {"Authorization": f"Bearer {client.get_token()}"}
    resp = requests.get(att["url"], headers=headers, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"下载失败 HTTP {resp.status_code}")
    tmp_dir = tempfile.mkdtemp(prefix="verify_pa_")
    pdf_path = os.path.join(tmp_dir, att["name"])
    with open(pdf_path, "wb") as f:
        f.write(resp.content)
    return pdf_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只分析不写回")
    ap.add_argument("--apply", action="store_true", help="实际写回")
    args = ap.parse_args()

    from insurance_agent.infrastructure.feishu_bitable_client import load_client_from_config
    from insurance_agent.infrastructure.parsers.pymupdf_parser import PyMuPDFParser

    client = load_client_from_config(load_feishu_config())
    analyzer = AIAnalyzer(llm_client=create_llm_client(), pdf_parser=PyMuPDFParser())
    writer = PolicyWriter(client)

    recs = client.list_records(INSURANCE_POLICY_TABLE, page_size=500)
    pending = [
        r for r in recs
        if not (r.get("fields") or {}).get("保险单号") and (r.get("fields") or {}).get("保单")
    ]
    print(f"待处理记录: {len(pending)} 条", flush=True)

    for r in pending:
        att = r["fields"]["保单"][0]
        print(f"\n=== {r['record_id']} 附件 {att['name']} ===", flush=True)
        pdf_path = _download(client, att)
        try:
            result = analyzer.analyze(pdf_path, file_name=att["name"])
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

            if args.apply and not result.get("error"):
                writer.write_policy_numbers(
                    r["record_id"],
                    result["main_policy_number"],
                    result["batch_policy_number"],
                )
                if result["persons"]:
                    writer.write_persons(result["persons"], result)
                print("已写回 ✓", flush=True)
        finally:
            try:
                os.remove(pdf_path)
                os.rmdir(os.path.dirname(pdf_path))
            except Exception:
                pass


if __name__ == "__main__":
    main()
