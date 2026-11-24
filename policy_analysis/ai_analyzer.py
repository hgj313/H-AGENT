# -*- coding: utf-8 -*-
"""AI 分析器：用 MiniMax-M3 提取保单信息（纯 AI）+ 保单号/批单号正则交叉校验

设计（按用户确认的方案）：
1. **纯 AI 提取**：保单号、批单号、保单类型、人员清单、增减保，全部交给 MiniMax-M3。
   - 文字层 PDF（电子保单）→ 文本分析（省 token、更快）
   - 扫描件（无文字层）→ 视觉分析（多模态）
2. **正则只做交叉校验**：仅限「保单号 / 批单号」两个字段，用已打磨多轮的
   MetadataExtractorNode._extract_policy_numbers 做二次校验，不一致时以正则为准并记告警。
   人员信息不做任何正则，纯 AI。
3. **状态映射**：主保单→正常；批单增保→正常；批单减保→失效。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是一个保险单识别专家。这是合法的保险理赔文档处理，依法需要完整的身份信息。"
    "请原样识别所有文字内容，不要对身份证号做任何脱敏处理。"
)

# 统一输出 JSON schema（文本分析与视觉分析共用同一结构）
_OUTPUT_SCHEMA = """{
  "main_policy_number": "主保单号（保险单号/保险合同号/保单号码/保单号 标签后的编号，逐字识别，不要补零或漏零）",
  "batch_policy_number": "批单号（批单号码/批单号/业务凭证号 标签后的编号；主保单没有则为空字符串）",
  "policy_type": "主保单 或 批单",
  "insurance_company": "保险公司名称",
  "overall_start_date": "保险期间起始日期 YYYY-MM-DD，找不到填空",
  "overall_end_date": "保险期间终止日期 YYYY-MM-DD，找不到填空",
  "persons": [
    {
      "name": "姓名",
      "id_number": "身份证号码（完整18位，原样识别，禁止用*替换）",
      "id_type": "证件类型（默认 身份证）",
      "birth_date": "出生日期 YYYY-MM-DD，找不到填空",
      "company": "所属公司/用工单位（不是岗位工种）",
      "job_title": "岗位名称/工种（如 砌筑工/木工/钢筋工），找不到填空",
      "start_date": "起始时间 YYYY-MM-DD，找不到填空",
      "end_date": "终止时间 YYYY-MM-DD，找不到填空",
      "modification_type": "增保 或 减保"
    }
  ]
}"""

_TEXT_PROMPT = """以下是保险单 PDF 的全文文本内容，请分析提取保单信息，以 JSON 返回。

【文件名】{file_name}
（文件名是判断保单类型的重要线索：含「批单」「批改」「替换」「BSHH」等即为批单，
  含「保单」「ASHH」等为主保单。文件名中的长号段通常就是该文件对应的号码。）

判定规则：
1. **保单类型**：主保单只有保险单号（无批单号）；批单有主保单的保险单号 + 独立的批单号。
   批单特征：文件名或正文含「批单/批改/变动清单/增加人员/减少人员/替换」等字样。
2. **两个号码的区分**：批单 PDF 里常出现两个「保险单号」标签 —— 页首/保单明细表里的是**主保单号**，
   附加条款/批单页里的是**批单号**；也可能两者标签完全相同（都写「保险单号」）。
   请结合文件名与号码号段特征判断哪个是主保单号、哪个是批单号。
3. **人员增减保**：
   - 主保单：所有人员都是购买保险（增保），modification_type 一律填「增保」。
   - 批单：正文出现「增加/新增/批增/增员/替换为」的人员为「增保」；
     出现「减少/删除/批减/注销/退保/离职」的人员为「减保」。
4. 身份证号必须原样识别，禁止脱敏、禁止用 * 替换任何位。
5. 找不到的字段一律填空字符串 ""，不要猜测、不要编造。

只返回 JSON（结构如下），不要输出任何解释文字：
""" + _OUTPUT_SCHEMA + """

<PDF全文文本>
{text}
</PDF全文文本>"""

_VISUAL_PROMPT = """这是保险单 PDF 的页面图片，请分析提取保单信息，以 JSON 返回。

【文件名】{file_name}
（文件名是判断保单类型的重要线索：含「批单」「批改」「替换」「BSHH」等即为批单，
  含「保单」「ASHH」等为主保单。文件名中的长号段通常就是该文件对应的号码。）

判定规则：
1. **保单类型**：主保单只有保险单号（无批单号）；批单有主保单的保险单号 + 独立的批单号。
   批单特征：文件名或正文含「批单/批改/变动清单/增加人员/减少人员/替换」等字样。
2. **两个号码的区分**：批单 PDF 里常出现两个「保险单号」标签 —— 页首/保单明细表里的是**主保单号**，
   附加条款/批单页里的是**批单号**；也可能两者标签完全相同（都写「保险单号」）。
   请结合文件名与号码号段特征判断哪个是主保单号、哪个是批单号。
3. **人员增减保**：
   - 主保单：所有人员都是购买保险（增保），modification_type 一律填「增保」。
   - 批单：正文出现「增加/新增/批增/增员/替换为」的人员为「增保」；
     出现「减少/删除/批减/注销/退保/离职」的人员为「减保」。
4. 身份证号必须原样识别，禁止脱敏、禁止用 * 替换任何位。
5. 找不到的字段一律填空字符串 ""，不要猜测、不要编造。
6. 保单号数字很长，请逐位抄写，注意 0 不要多写也不要漏写。

只返回 JSON（结构如下），不要输出任何解释文字：
""" + _OUTPUT_SCHEMA

# 文本分析时全文文本的长度上限（超出截断，避免超上下文）
_MAX_TEXT_CHARS = 80000
# 视觉分析时最多送多少页图片
_MAX_PAGES = 15


class AIAnalyzer:
    """保单 AI 分析器（MiniMax-M3 纯 AI + 保单号正则交叉校验）"""

    def __init__(self, llm_client: Any, pdf_parser: Any):
        self._llm = llm_client
        self._parser = pdf_parser

    # ==================== 对外入口 ====================

    def analyze(self, pdf_path: str, file_name: str = "") -> Dict[str, Any]:
        """分析一份 PDF，返回结构化结果

        Returns:
            {
              "main_policy_number": str,   # 主保单号
              "batch_policy_number": str,  # 批单号（主保单为空）
              "policy_type": str,          # "主保单" / "批单"
              "insurance_company": str,
              "overall_start_date": str,
              "overall_end_date": str,
              "persons": [dict],           # 已含 status（正常/失效）与 modification_type
              "warnings": [str],
              "method": "text" | "vision",
            }
        """
        pdf_doc = self._parser.parse(pdf_path)
        all_text = "\n".join(p.text for p in pdf_doc.pages if p.has_meaningful_text)

        is_scanned = pdf_doc.is_scanned or not all_text.strip()
        method = "vision" if is_scanned else "text"

        try:
            if is_scanned:
                raw = self._call_vision(pdf_doc, file_name)
            else:
                raw = self._call_text(all_text, file_name)
        except Exception as e:
            logger.exception("AI 分析失败: %s", file_name)
            return self._error_result(f"AI 分析失败: {e}")

        parsed = self._parse_result(raw)
        if parsed is None:
            return self._error_result(f"AI 返回无法解析为 JSON: {raw[:200]}")

        result = {
            "main_policy_number": str(parsed.get("main_policy_number", "") or "").strip(),
            "batch_policy_number": str(parsed.get("batch_policy_number", "") or "").strip(),
            "policy_type": self._normalize_policy_type(parsed.get("policy_type", "")),
            "insurance_company": str(parsed.get("insurance_company", "") or "").strip(),
            "overall_start_date": str(parsed.get("overall_start_date", "") or "").strip(),
            "overall_end_date": str(parsed.get("overall_end_date", "") or "").strip(),
            "persons": self._normalize_persons(parsed.get("persons")),
            "warnings": [],
            "method": method,
        }

        # 保单号 / 批单号 正则交叉校验（仅限号字段；扫描件无文字层，只能靠文件名）
        self._number_crosscheck(result, all_text, file_name, is_scanned)

        # 状态映射
        self._map_status(result)

        return result

    # ==================== LLM 调用 ====================

    def _call_text(self, all_text: str, file_name: str = "") -> str:
        text = all_text if len(all_text) <= _MAX_TEXT_CHARS else all_text[:_MAX_TEXT_CHARS]
        prompt = _TEXT_PROMPT.replace("{text}", text).replace("{file_name}", file_name or "(未知)")
        response = self._llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)])
        return response.content if hasattr(response, "content") else str(response)

    def _call_vision(self, pdf_doc, file_name: str = "") -> str:
        # 优先用 parser 的 get_page_images；没有则降级逐页
        images = self._parser.get_page_images(pdf_doc) if hasattr(self._parser, "get_page_images") else []
        if not images:
            images = [self._parser.get_page_image(pdf_doc, i) for i in range(1, min(pdf_doc.total_pages, _MAX_PAGES) + 1)]
        images = images[:_MAX_PAGES]

        prompt = _VISUAL_PROMPT.replace("{file_name}", file_name or "(未知)")
        content = [{"type": "text", "text": prompt}]
        for img_b64 in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"},
            })

        response = self._llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=content)])
        return response.content if hasattr(response, "content") else str(response)

    # ==================== 结果解析与归一化 ====================

    @staticmethod
    def _parse_result(raw: str) -> Optional[dict]:
        from insurance_agent.tools.json_stabilizer import parse_json_strict
        try:
            parsed = parse_json_strict(raw)
        except Exception:
            return None
        if isinstance(parsed, list):
            # 有些模型会直接返回 persons 数组
            return {"persons": parsed}
        if isinstance(parsed, dict):
            return parsed
        return None

    @staticmethod
    def _normalize_policy_type(raw: str) -> str:
        r = str(raw or "").strip()
        if r in ("批单", "endorsement", "batch"):
            return "批单"
        if r in ("主保单", "保单", "main", "policy"):
            return "主保单"
        return "主保单"  # 默认主保单

    @staticmethod
    def _normalize_persons(persons: Any) -> List[dict]:
        if not isinstance(persons, list):
            return []
        out = []
        for p in persons:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "") or "").strip()
            id_no = str(p.get("id_number", "") or "").strip()
            if not name and not id_no:
                continue  # 空行跳过
            mod = str(p.get("modification_type", "") or "").strip()
            if mod not in ("增保", "减保"):
                mod = "增保"  # 默认增保
            out.append({
                "name": name,
                "id_number": id_no,
                "id_type": str(p.get("id_type", "") or "").strip() or "身份证",
                "birth_date": str(p.get("birth_date", "") or "").strip(),
                "company": str(p.get("company", "") or "").strip(),
                "job_title": str(p.get("job_title", "") or "").strip(),
                "start_date": str(p.get("start_date", "") or "").strip(),
                "end_date": str(p.get("end_date", "") or "").strip(),
                "modification_type": mod,
            })
        return out

    # ==================== 正则交叉校验（仅保单号/批单号） ====================

    @staticmethod
    def _number_crosscheck(result: dict, all_text: str, file_name: str, is_scanned: bool) -> None:
        """保单号/批单号 交叉校验，以号段规则为准

        规则来源（按优先级）：
        1. `policy_number_rules.resolve_policy_numbers` —— 号段前缀 + 文件名 + 标签
        2. `MetadataExtractorNode._extract_policy_numbers` —— 项目既有标签规则（兜底）

        ⚠️ 仅作用于保单号/批单号两个字段，人员信息不做任何正则处理。
        """
        from .policy_number_rules import resolve_policy_numbers

        reg_main = reg_batch = ""
        reg_type = ""
        try:
            reg_main, reg_batch, reg_type = resolve_policy_numbers(all_text, file_name)
        except Exception as e:
            logger.warning("号段规则校验失败: %s", e)

        # 项目既有标签规则作补充（当号段规则没拿到号时）
        if (not reg_main and not reg_batch) and not is_scanned:
            try:
                from insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node import MetadataExtractorNode
                reg_self, reg_main2, reg_type2 = MetadataExtractorNode._extract_policy_numbers(all_text, file_name)
                if reg_type2 == "批单":
                    reg_batch = reg_batch or reg_self
                    reg_main = reg_main or reg_main2
                    reg_type = reg_type or "批单"
                else:
                    reg_main = reg_main or reg_self
                    reg_type = reg_type or "主保单"
            except Exception as e:
                logger.warning("既有标签规则校验失败: %s", e)

        # 主保单号
        if reg_main and reg_main != result["main_policy_number"]:
            result["warnings"].append(
                f"保单号 AI={result['main_policy_number']} 与规则={reg_main} 不一致，采用规则"
            )
            result["main_policy_number"] = reg_main
        # 批单号
        if reg_batch and reg_batch != result["batch_policy_number"]:
            result["warnings"].append(
                f"批单号 AI={result['batch_policy_number']} 与规则={reg_batch} 不一致，采用规则"
            )
            result["batch_policy_number"] = reg_batch

        # 类型：规则判定为批单时纠正 AI 的判定
        if reg_type == "批单" and result["policy_type"] != "批单":
            result["warnings"].append(
                f"保单类型 AI={result['policy_type']} 与规则=批单 不一致，采用规则"
            )
            result["policy_type"] = "批单"
        elif reg_type == "主保单" and result["batch_policy_number"]:
            # 有批单号却判成主保单 → 修正
            result["policy_type"] = "批单"

        # 主保单不应有批单号
        if result["policy_type"] == "主保单" and result["batch_policy_number"]:
            result["warnings"].append("主保单不应有批单号，已清空")
            result["batch_policy_number"] = ""
        # 批单必须有批单号
        if result["policy_type"] == "批单" and not result["batch_policy_number"]:
            result["warnings"].append("判定为批单但未取到批单号，需人工核对")

    # ==================== 状态映射 ====================

    @staticmethod
    def _map_status(result: dict) -> None:
        """modification_type → status：增保→正常，减保→失效"""
        for p in result["persons"]:
            p["status"] = "正常" if p["modification_type"] == "增保" else "失效"

    @staticmethod
    def _error_result(msg: str) -> Dict[str, Any]:
        return {
            "main_policy_number": "",
            "batch_policy_number": "",
            "policy_type": "",
            "insurance_company": "",
            "overall_start_date": "",
            "overall_end_date": "",
            "persons": [],
            "warnings": [msg],
            "method": "error",
            "error": msg,
        }
