"""Node 2: MetadataExtractorNode

职责：
- 从 PDF 全文档文字中提取保单号、整体保险期间、投保人公司名
- 定位人员清单所在页
- 决策 format_hint（table / inline / ocr）
"""

import re
from insurance_agent.domain import PDFDocument
from insurance_agent.tools import (
    extract_company_after_label,
    extract_overall_insurance_period,
    extract_company_name,
)
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState


# 人员清单页定位标记
_LIST_MARKERS = ["人员清单", "雇员清单", "雇员人名清单", "人名清单", "被保险人清单", "员工清单", "被保险人名单"]
# 行内格式标记
_INLINE_MARKERS = ["雇员姓名：", "雇员姓名:", "雇员姓名：", "雇员姓名:"]


class MetadataExtractorNode:
    """元数据提取节点（无外部依赖，纯规则）"""

    def __call__(self, state: InvoiceRecognitionState) -> dict:
        pdf_doc_dict = state.get("pdf_document")
        if not pdf_doc_dict:
            return {
                "status": "error",
                "error": "missing_pdf_document",
                "next_action": "finish",
            }

        # 重建 PDFDocument
        pdf_doc = PDFDocument(**{k: v for k, v in pdf_doc_dict.items() if k != "pages"})
        # pages 字段是 list[dict]，重建为 PDFPage
        from insurance_agent.domain import PDFPage
        pdf_doc.pages = [PDFPage(**p) for p in pdf_doc_dict.get("pages", [])]

        all_text = " ".join(p.text for p in pdf_doc.pages if p.has_meaningful_text)

        # 1. 保单号
        policy_number = self._extract_policy_number(all_text)

        # 2. 整体保险期间
        overall_start, overall_end = extract_overall_insurance_period(all_text)

        # 3. 投保人公司名
        policy_holder = extract_company_after_label(all_text) or extract_company_name(all_text) or ""

        # 4. 人员清单页定位
        list_pages = self._find_list_pages(pdf_doc)

        # 5. 决策 format_hint
        if state.get("is_scanned"):
            format_hint = "ocr"
        elif any(marker in all_text for marker in _INLINE_MARKERS):
            format_hint = "inline"
        elif list_pages:
            format_hint = "table"
        else:
            format_hint = "ocr"  # 兜底走 OCR

        return {
            "status": "executing",
            "policy_holder": policy_holder,
            "list_pages": list_pages,
            "format_hint": format_hint,
            "tool_results": {
                **state.get("tool_results", {}),
                "metadata_extractor": {
                    "policy_number": policy_number,
                    "overall_start_date": overall_start,
                    "overall_end_date": overall_end,
                    "policy_holder": policy_holder,
                    "list_pages": list_pages,
                    "format_hint": format_hint,
                },
            },
            "working_memory": {
                **state.get("working_memory", {}),
                "policy_number": policy_number,
                "overall_start_date": overall_start,
                "overall_end_date": overall_end,
            },
        }

    @staticmethod
    def _extract_policy_number(text: str) -> str:
        patterns = [
            r"保险单号[：:\s]*([A-Za-z0-9]{10,30})",
            r"保单号[：:\s]*([A-Za-z0-9]{10,30})",
            r"保单流水号[：:\s]*([A-Za-z0-9]{10,30})",
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _find_list_pages(pdf_doc: PDFDocument) -> list[int]:
        result = []
        list_page_nums = []
        for page in pdf_doc.pages:
            if not page.has_meaningful_text:
                continue
            for marker in _LIST_MARKERS:
                if marker in page.text:
                    list_page_nums.append(page.page_number)
                    break
            else:
                for marker in _INLINE_MARKERS:
                    if marker in page.text:
                        list_page_nums.append(page.page_number)
                        break

        # 扩展：包含清单页后续页面（跨页人员清单）
        # 如果后续页面包含身份证号片段（6+连续数字）或"方案"标记，也纳入
        import re as _re
        for lpn in list_page_nums:
            if lpn not in result:
                result.append(lpn)
            # 检查后续页面
            for page in pdf_doc.pages:
                if page.page_number <= lpn:
                    continue
                if page.page_number in result:
                    continue
                if not page.has_meaningful_text:
                    continue
                # 包含 6+ 连续数字 或 "方案" 标记 → 可能是清单续页
                if _re.search(r'\d{6,}', page.text) or '方案' in page.text:
                    # 但排除条款页（通常以 "-" 开头或包含 "条款" "第.*条"）
                    if '条款' not in page.text and '第一条' not in page.text:
                        result.append(page.page_number)
                else:
                    break  # 遇到非清单页就停止
        return sorted(result)


def metadata_extractor_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
