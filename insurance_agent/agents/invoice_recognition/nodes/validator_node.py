"""Node 4: ValidatorNode

职责：
- 补全被脱敏的身份证号（用出生日期填充）
- 批单关联主保单：查找主保单补全起止时间
- 校验人员数据完整性
- 收集 warnings / errors
- 决定 next_action（continue / retry / finish）
"""

import logging
from insurance_agent.domain import InsuredPerson
from insurance_agent.tools import reconstruct_persons_ids, is_masked_id, parse_policy_filename
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState

logger = logging.getLogger(__name__)


class ValidatorNode:
    """校验节点

    DI：可选注入 PolicyLibrary，用于批单关联主保单补全起止时间。
    """

    def __init__(self, policy_library=None):
        self._policy_library = policy_library

    def __call__(self, state: InvoiceRecognitionState) -> dict:
        result_dict = state.get("extraction_result") or {}
        persons_dicts = result_dict.get("insured_persons", [])

        # --- 身份证号补全 ---
        persons = [InsuredPerson(**p) for p in persons_dicts]
        reconstruction_warnings = reconstruct_persons_ids(persons)

        for i, p in enumerate(persons):
            if persons_dicts[i].get("id_number") != p.id_number:
                persons_dicts[i]["id_number"] = p.id_number
            persons_dicts[i]["birth_date"] = p.birth_date

        # --- 批单关联主保单：补全起止时间 ---
        link_warnings = self._link_to_main_policy(state, result_dict, persons_dicts)

        # --- 完整性校验 ---
        warnings = list(reconstruction_warnings) + list(link_warnings)
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

    def _link_to_main_policy(self, state, result_dict, persons_dicts) -> list[str]:
        """批单关联主保单，补全起止时间

        当当前文件是批单类型时：
        1. 从文件名解析判断是否为批单
        2. 用保单号在 PolicyLibrary 中查找主保单
        3. 用主保单的起止时间填充批单中缺失的起止时间
        """
        warnings = []

        if not self._policy_library:
            return warnings

        file_name = result_dict.get("file_name", "")
        fname_info = parse_policy_filename(file_name)

        # 只处理批单类型
        if fname_info.policy_type != "批单":
            return warnings

        policy_number = result_dict.get("policy_number", "")
        company = result_dict.get("policy_holder", "") or fname_info.company

        # 查找主保单
        main_policy = self._policy_library.find_main_policy(
            policy_number=policy_number,
            company=company,
        )

        if not main_policy:
            warnings.append(
                f"批单未找到对应主保单: policy_number={policy_number}, company={company}"
            )
            return warnings

        # 用主保单的起止时间填充缺失的时间
        main_start = main_policy.start_date
        main_end = main_policy.end_date
        main_insurance_company = main_policy.insurance_company

        filled_count = 0
        for p_dict in persons_dicts:
            if not p_dict.get("start_date") and main_start:
                p_dict["start_date"] = main_start
                filled_count += 1
            if not p_dict.get("end_date") and main_end:
                p_dict["end_date"] = main_end
                filled_count += 1

        # 补全保险公司名
        if result_dict.get("insurance_company") in ("", "unknown") and main_insurance_company:
            result_dict["insurance_company"] = main_insurance_company

        # 补全整体保险期间
        if not result_dict.get("overall_start_date") and main_start:
            result_dict["overall_start_date"] = main_start
        if not result_dict.get("overall_end_date") and main_end:
            result_dict["overall_end_date"] = main_end

        if filled_count > 0:
            logger.info(
                f"批单 {file_name} 关联主保单 {main_policy.file_name}，"
                f"补全 {filled_count} 个时间字段"
            )

        return warnings


def validator_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
