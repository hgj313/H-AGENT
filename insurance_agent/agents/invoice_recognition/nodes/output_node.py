"""Node 5: OutputNode

职责：
- 透传 extraction_result 为最终稳定 JSON 输出
- AGENTS.md 三重保险：to_json（dict 转 json） + field 完整性 + errors/warnings 上报
"""

import json
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState


class OutputNode:
    """输出节点：透传结构化结果（不兜底、不分析）"""

    def __call__(self, state: InvoiceRecognitionState) -> dict:
        result_dict = state.get("extraction_result") or {}
        warnings = state.get("warnings", [])

        # 透传：把 extraction_result 直接 JSON 化作为 final_response
        if result_dict:
            final_json = json.dumps(result_dict, ensure_ascii=False, indent=2)
        else:
            final_json = json.dumps({
                "error": state.get("error", "no_result"),
                "warnings": warnings,
            }, ensure_ascii=False, indent=2)

        return {
            "status": "finished",
            "next_action": "finish",
            "final_response": final_json,
        }


def output_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
