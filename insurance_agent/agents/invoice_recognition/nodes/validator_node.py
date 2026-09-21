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
        """批单关联主保单，补全起止时间（2026-09-21 增强）

        当当前文件是批单类型时（由 metadata_extractor 基于 PDF 文本判定，不再仅靠文件名）：
        1. 优先用 result_dict["main_policy_number"]（PDF"保险单号"标签）在主保单表精确查找
        2. fallback：用 policy_number（批单号）+ company 在主保单表兼容查找
        3. 用主保单的起止时间 + 批单生效日填充批单中缺失的起止时间

        关键修复（刘红才(1).pdf, 2026-09-21）：
          - 文件名 `刘红才(1).pdf` 不含"批单"/"BD"，旧逻辑会跳过；新逻辑用 metadata_extractor
            写入的 `working_memory["policy_type"]=="批单"` 判定。
        """
        warnings = []

        if not self._policy_library:
            return warnings

        file_name = result_dict.get("file_name", "")
        fname_info = parse_policy_filename(file_name)

        # 1. 判定是否批单：优先用 metadata_extractor 基于 PDF 文本的判定
        policy_type = (
            state.get("working_memory", {}).get("policy_type")
            or result_dict.get("policy_type")
            or fname_info.policy_type
        )
        if policy_type != "批单":
            return warnings

        # 2. 取保单号（批单号 / 主保单号 / 公司名）
        batch_policy_number = (
            state.get("working_memory", {}).get("batch_policy_number")
            or result_dict.get("batch_policy_number")
            or result_dict.get("policy_number", "")
        )
        main_policy_number = (
            state.get("working_memory", {}).get("main_policy_number")
            or result_dict.get("main_policy_number")
            or ""
        )
        company = result_dict.get("policy_holder", "") or fname_info.company
        endorsement_effective_date = (
            state.get("working_memory", {}).get("endorsement_effective_date")
            or result_dict.get("endorsement_effective_date")
            or ""
        )

        # 3. 查找主保单（优先用 main_policy_number 在主保单表精确查找）
        main_policy = None
        if main_policy_number:
            main_policy = self._policy_library.find_main_policy_by_number(main_policy_number)
        if not main_policy and batch_policy_number:
            # 兼容性查找：用批单号去主保单表按 prefix 匹配
            main_policy = self._policy_library.find_main_policy_by_company_compatible(
                company=company or "UNKNOWN",
                batch_policy_number=batch_policy_number,
            )
            # 兼容性版本只在有 company 时过滤；如果没传 company，回退到精确查找
            if not main_policy and not company:
                # 按号段规律推主保单号
                if len(batch_policy_number) >= 20 and batch_policy_number[0] == "7":
                    inferred_main = "8" + batch_policy_number[1:]
                    main_policy = self._policy_library.find_main_policy_by_number(inferred_main)

        if not main_policy:
            warnings.append(
                f"批单未找到对应主保单: main={main_policy_number}, batch={batch_policy_number}, company={company}"
            )
            return warnings

        # 4. 安全校验（2026-09-15 关键 + 2026-09-18 加固 + 2026-09-21 简化）：
        # 找到的主保单号必须与 main_policy_number 或批单号前缀兼容
        if main_policy_number and main_policy.policy_number != main_policy_number:
            if batch_policy_number and not self._policy_library._policy_numbers_compatible(
                batch_policy_number, main_policy.policy_number
            ):
                warnings.append(
                    f"批单关联的主保单号({main_policy.policy_number})与批单的主保单号({main_policy_number})不兼容，"
                    f"跳过日期补全。"
                )
                logger.warning(
                    f"批单 {file_name} 期望主保单号 {main_policy_number}，"
                    f"但查找到 {main_policy.policy_number}，保单号前缀不兼容，拒绝日期补全"
                )
                return warnings

        # 5. 用主保单的起止时间 + 批单生效日填充缺失时间
        main_start = main_policy.start_date
        main_end = main_policy.end_date
        main_insurance_company = main_policy.insurance_company

        # 增保 start_date 优先用批单生效日（合同实际变动日），
        # fallback 到主保单起期（兼容历史批单数据）；
        # end_date 用主保单止期（增保人员在保单期内有效）
        added_start = endorsement_effective_date or main_start

        filled_count = 0
        for p_dict in persons_dicts:
            mod_type = p_dict.get("modification_type", "增保")
            if mod_type == "减保":
                # 减保：end_date 用批单生效日（已是合同行为边界）
                if not p_dict.get("end_date") and endorsement_effective_date:
                    p_dict["end_date"] = endorsement_effective_date
                    filled_count += 1
                # start_date 用主保单起期（如果缺失）
                if not p_dict.get("start_date") and main_start:
                    p_dict["start_date"] = main_start
                    filled_count += 1
            else:
                # 增保
                if not p_dict.get("start_date") and added_start:
                    p_dict["start_date"] = added_start
                    filled_count += 1
                if not p_dict.get("end_date") and main_end:
                    p_dict["end_date"] = main_end
                    filled_count += 1

        # 补全保险公司名
        if result_dict.get("insurance_company") in ("", "unknown") and main_insurance_company:
            result_dict["insurance_company"] = main_insurance_company

        # 补全整体保险期间（写到 result_dict 供 _persist_policy_result 使用）
        if not result_dict.get("overall_start_date") and added_start:
            result_dict["overall_start_date"] = added_start
        if not result_dict.get("overall_end_date") and main_end:
            result_dict["overall_end_date"] = main_end

        if filled_count > 0:
            logger.info(
                f"批单 {file_name} 关联主保单 {main_policy.file_name}（{main_policy.policy_number}），"
                f"补全 {filled_count} 个时间字段（批单生效日={endorsement_effective_date}）"
            )

        return warnings


def validator_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
