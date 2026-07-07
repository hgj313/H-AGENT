"""Node 4: ValidatorNode

职责：
- 补全被脱敏的身份证号（用出生日期填充）
- 校验人员数据完整性
- 收集 warnings / errors
- 决定 next_action（continue / retry / finish）
"""

from insurance_agent.domain import InsuredPerson
from insurance_agent.tools import reconstruct_persons_ids, is_masked_id
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState


class ValidatorNode:
    """校验节点（纯规则，不依赖外部）"""

    def __call__(self, state: InvoiceRecognitionState) -> dict:
        result_dict = state.get("extraction_result") or {}
        persons_dicts = result_dict.get("insured_persons", [])

        # --- 身份证号补全 ---
        # 将 dict 列表转为 InsuredPerson 对象，执行补全，再写回 dict
        persons = [InsuredPerson(**p) for p in persons_dicts]
        reconstruction_warnings = reconstruct_persons_ids(persons)

        # 将补全后的 id_number 写回 dict
        for i, p in enumerate(persons):
            if persons_dicts[i].get("id_number") != p.id_number:
                persons_dicts[i]["id_number"] = p.id_number
            persons_dicts[i]["birth_date"] = p.birth_date

        # --- 完整性校验 ---
        warnings = list(reconstruction_warnings)
        for p_dict in persons_dicts:
            if not p_dict.get("name"):
                warnings.append(f"缺少姓名: ID={p_dict.get('id_number')}")
            if not p_dict.get("id_number"):
                warnings.append(f"缺少证件号码: 姓名={p_dict.get('name')}")
            elif is_masked_id(p_dict.get("id_number", "")):
                warnings.append(f"身份证号仍被脱敏且无法补全: {p_dict.get('name')} (ID={p_dict.get('id_number')})")

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
            "extraction_result": result_dict,
        }


def validator_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
