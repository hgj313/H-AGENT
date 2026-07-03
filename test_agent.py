"""端到端测试：通过 LangGraph 跑通 Agent 管线

透传 Agent 行为，不做兜底分析。
扫描件 PDF 走 Phase 3 OCR（需要 DASHSCOPE_API_KEY 环境变量）。
"""

import json
import sys
import os

sys.path.insert(0, "C:/insurance-automation")

from dotenv import load_dotenv
load_dotenv("C:/insurance-automation/H-AGENT/.env")

from insurance_agent.infrastructure.parsers import PyMuPDFParser
from insurance_agent.agents.invoice_recognition import (
    InvoiceRecognitionCapability,
    create_invoice_recognition_state,
    build_invoice_recognition_graph,
)
from insurance_agent.infrastructure.llm.factory import LLMConfig, LLMProvider, create_llm


def get_llm_client():
    """创建 kimi-k2.6 视觉模型客户端（失败抛异常，不兜底）"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("DASHSCOPE_BASE_URL")
    if not api_key:
        print("  [WARN] DASHSCOPE_API_KEY 未配置，扫描件 OCR 将不可用")
        return None

    config = LLMConfig(
        provider=LLMProvider.DASHSCOPE,
        model_name="kimi-k2.6",
        api_key=api_key,
        base_url=base_url,
    )
    return create_llm(config)


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


if __name__ == "__main__":
    # 尝试创建 LLM 客户端（扫描件 OCR 需要）
    llm_client = None
    try:
        llm_client = get_llm_client()
        print("[OK] LLM 客户端创建成功（kimi-k2.6）")
    except Exception as e:
        print(f"[WARN] LLM 客户端创建失败: {e}")
        print("      文字层 PDF 仍可正常提取，扫描件将跳过 OCR")

    files = [
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/批单_重庆选鹏建筑工程有限公司_7116013100260058791001(2).pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/保单_重庆森炜建筑劳务有限公司_8116013100260072423000.pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/保单/保单_成都兴久隆钢结构工程有限公司_ASHH07037126FN004WAV(2).pdf",
        "D:/工作资料/2026/6月/AI项目/AI保险/南京大千装饰工程有限公司保单.pdf",
    ]

    results = []
    for fpath in files:
        print("=" * 70)
        print(f"文件: {fpath.split('/')[-1]}")
        print("=" * 70)

        try:
            final_state = run_agent(fpath, llm_client=llm_client)

            # 透传 final_response（agent 输出的最终 JSON）
            print(final_state.get("final_response", "{}"))

            # 记录结果
            result_dict = final_state.get("extraction_result") or {
                "file_name": fpath.split("/")[-1],
                "error": final_state.get("error"),
            }
            results.append(result_dict)

        except Exception as e:
            print(f"Agent 执行失败: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "file_name": fpath.split("/")[-1],
                "error": str(e),
            })

    # 保存汇总
    out_path = "C:/insurance-automation/extraction_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 70)
    print(f"已保存汇总: {out_path}")
    print("=" * 70)
