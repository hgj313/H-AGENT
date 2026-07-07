"""端到端测试：批量提取保险单被保人员信息

支持功能：
- 批量上传多个 PDF 保单文件
- 自动识别保险公司
- 自动识别增保/减保类型
- 所有被保人信息汇总到一个 CSV 表格
- 身份证号脱敏自动补全（用出生日期）

透传 Agent 行为，不做兜底分析。
扫描件 PDF 走 MiniMax-M3 多模态视觉模型 OCR。
"""

import json
import sys
import os
import csv

sys.path.insert(0, "C:/insurance-automation")

from dotenv import load_dotenv
load_dotenv("C:/insurance-automation/H-AGENT/.env")

from insurance_agent.infrastructure.parsers import PyMuPDFParser
from insurance_agent.agents.invoice_recognition import (
    InvoiceRecognitionCapability,
    create_invoice_recognition_state,
    build_invoice_recognition_graph,
)
from insurance_agent.infrastructure.llm.factory import create_minimax_llm_from_env
from insurance_agent.domain import ExtractionResult, InsuredPerson


def get_llm_client():
    """创建 MiniMax-M3 多模态模型客户端（失败抛异常，不兜底）"""
    return create_minimax_llm_from_env()


def run_agent(pdf_path: str, llm_client=None) -> dict:
    """运行 Agent 识别单份保单"""
    pdf_parser = PyMuPDFParser()
    capability = InvoiceRecognitionCapability(pdf_parser=pdf_parser, llm_client=llm_client)
    graph = build_invoice_recognition_graph(capability)

    initial_state = create_invoice_recognition_state(
        user_goal=f"提取 {pdf_path} 中的被保人员清单",
        file_path=pdf_path,
    )

    final_state = graph.invoke(initial_state)
    return final_state


def export_unified_csv(results: list[dict], output_path: str):
    """将所有提取结果汇总到一个 CSV 表格"""
    all_rows = []
    for result_dict in results:
        if result_dict.get("error"):
            continue

        result = ExtractionResult(
            file_name=result_dict.get("file_name", ""),
            insurance_company=result_dict.get("insurance_company", ""),
            policy_number=result_dict.get("policy_number", ""),
            overall_start_date=result_dict.get("overall_start_date", ""),
            overall_end_date=result_dict.get("overall_end_date", ""),
            insured_persons=[InsuredPerson(**p) for p in result_dict.get("insured_persons", [])],
        )
        all_rows.extend(result.to_csv_rows())

    if not all_rows:
        print("[WARN] 无数据可导出 CSV")
        return

    fieldnames = [
        "姓名", "证件号码", "证件类型", "出生日期",
        "所属公司", "批改类型",
        "起始时间", "起止时间",
        "岗位名称", "保险公司", "保单号", "来源文件",
    ]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"[CSV] 已导出 {len(all_rows)} 条记录 → {output_path}")


def print_summary(results: list[dict]):
    """打印汇总统计"""
    print()
    print("=" * 80)
    print("汇总统计")
    print("=" * 80)

    total_persons = 0
    total_add = 0
    total_remove = 0
    total_errors = 0

    for r in results:
        fname = r.get("file_name", "?")
        if r.get("error"):
            print(f"  [ERROR] {fname}: {r['error']}")
            total_errors += 1
            continue

        persons = r.get("insured_persons", [])
        add_count = sum(1 for p in persons if p.get("modification_type") == "增保")
        remove_count = sum(1 for p in persons if p.get("modification_type") == "减保")
        other_count = len(persons) - add_count - remove_count

        insurance_co = r.get("insurance_company", "unknown")
        print(f"  [{insurance_co}] {fname}")
        print(f"    人数: {len(persons)} (增保: {add_count}, 减保: {remove_count}, 其他: {other_count})")

        total_persons += len(persons)
        total_add += add_count
        total_remove += remove_count

    print(f"\n  总计: {total_persons} 人 (增保: {total_add}, 减保: {total_remove}), 错误: {total_errors}")
    print("=" * 80)


if __name__ == "__main__":
    # 尝试创建 LLM 客户端（扫描件 OCR 需要）
    llm_client = None
    try:
        llm_client = get_llm_client()
        print("[OK] LLM 客户端创建成功（MiniMax-M3 多模态）")
    except Exception as e:
        print(f"[WARN] LLM 客户端创建失败: {e}")
        print("      文字层 PDF 仍可正常提取，扫描件将跳过 OCR")

    # 批量 PDF 文件列表
    files = [
        # 旧测试文件
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/批单_重庆选鹏建筑工程有限公司_7116013100260058791001(2).pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/保单_重庆森炜建筑劳务有限公司_8116013100260072423000.pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/保单_成都兴久隆钢结构工程有限公司_ASHH07037126FN004WAV(2).pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/南京大千装饰工程有限公司保单.pdf",
        # 新增测试文件
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/替换9人·批增2人保单·广州粤灿0624.pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/保单_深圳市祥胜建设有限公司_668701202644017100008803.pdf",
    ]

    results = []
    for fpath in files:
        print("=" * 70)
        print(f"文件: {os.path.basename(fpath)}")
        print("=" * 70)

        try:
            final_state = run_agent(fpath, llm_client=llm_client)

            # 透传 final_response（agent 输出的最终 JSON）
            print(final_state.get("final_response", "{}"))

            # 记录结果
            result_dict = final_state.get("extraction_result") or {
                "file_name": os.path.basename(fpath),
                "error": final_state.get("error"),
            }
            results.append(result_dict)

        except Exception as e:
            print(f"Agent 执行失败: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "file_name": os.path.basename(fpath),
                "error": str(e),
            })

    # 保存 JSON 汇总
    json_path = "C:/insurance-automation/extraction_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 导出统一 CSV 表格
    csv_path = "C:/insurance-automation/extraction_results.csv"
    export_unified_csv(results, csv_path)

    # 打印汇总
    print_summary(results)

    print(f"\nJSON: {json_path}")
    print(f"CSV:  {csv_path}")
