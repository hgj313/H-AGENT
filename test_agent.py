"""端到端测试：通过 LangGraph 跑通 Agent 管线

透传 Agent 行为，不做兜底分析。
"""

import json
import sys

sys.path.insert(0, "C:/insurance-automation")

from insurance_agent.infrastructure.parsers import PyMuPDFParser
from insurance_agent.agents.invoice_recognition import (
    InvoiceRecognitionCapability,
    create_invoice_recognition_state,
    build_invoice_recognition_graph,
)


def run_agent(pdf_path: str) -> dict:
    """运行 Agent 识别单份保单"""
    pdf_parser = PyMuPDFParser()
    capability = InvoiceRecognitionCapability(pdf_parser=pdf_parser)
    graph = build_invoice_recognition_graph(capability)

    initial_state = create_invoice_recognition_state(
        user_goal=f"提取 {pdf_path} 中的被保人员清单",
        file_path=pdf_path,
    )

    final_state = graph.invoke(initial_state)
    return final_state


if __name__ == "__main__":
    files = [
        "D:/工作资料/2026/6月/AI项目/AI保险/南京大千装饰工程有限公司保单.pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/批单_重庆选鹏建筑工程有限公司_7116013100260058791001(2).pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/保单_重庆森炜建筑劳务有限公司_8116013100260072423000.pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/保单_成都兴久隆钢结构工程有限公司_ASHH07037126FN004WAV(2).pdf",
    ]

    results = []
    for fpath in files:
        print("=" * 70)
        print(f"文件: {fpath.split('/')[-1]}")
        print("=" * 70)

        final_state = run_agent(fpath)

        # 透传 final_response（agent 输出的最终 JSON）
        print(final_state.get("final_response", "{}"))
        print()

        # 同时记录 extraction_result 供后续汇总
        result_dict = final_state.get("extraction_result") or {
            "file_name": fpath.split("/")[-1],
            "error": final_state.get("error"),
        }
        results.append(result_dict)

    # 保存汇总
    with open("C:/insurance-automation/extraction_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print(f"已保存汇总: C:/insurance-automation/extraction_results.json")
    print("=" * 70)
