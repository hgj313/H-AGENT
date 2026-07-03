"""Node 4: ValidatorNode

职责：
- 校验人员数据完整性
- 收集 warnings / errors
- 决定 next_action（continue / retry / finish）
"""

from insurance_agent.domain import InsuredPerson
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState


class ValidatorNode:
    """校验节点（纯规则，不依赖外部）"""

    def __call__(self, state: InvoiceRecognitionState) -> dict:
        result_dict = state.get("extraction_result") or {}
        persons_dicts = result_dict.get("insured_persons", [])

        warnings = []
        for p_dict in persons_dicts:
            if not p_dict.get("name"):
                warnings.append(f"缺少姓名: ID={p_dict.get('id_number')}")
            if not p_dict.get("id_number"):
                warnings.append(f"缺少证件号码: 姓名={p_dict.get('name')}")

        if not persons_dicts and state.get("format_hint") != "ocr":
            return {
                "status": "error",
                "next_action": "finish",
                "warnings": warnings,
                "error": "no_persons_extracted",
            }

        return {
            "status": "reviewing",
            "next_action": "continue",
            "warnings": warnings,
        }


def validator_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
