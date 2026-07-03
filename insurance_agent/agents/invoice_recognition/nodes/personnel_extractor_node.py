"""Node 3: PersonnelExtractorNode

职责：
- 根据 format_hint 选择对应 Extractor
- 从 list_pages 提取 InsuredPerson
- 缺日期时用整体保险期间兜底

DI：所有 Extractor 通过构造器注入。OCR 走视觉模型（Phase 3）。
"""

from typing import Optional
from insurance_agent.domain import PDFDocument, InsuredPerson, ExtractionResult
from insurance_agent.extractors import BaseExtractor, TableExtractor, InlineExtractor
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState


class PersonnelExtractorNode:
    """人员提取节点

    DI：注入三种 Extractor（table / inline / ocr）。
    """

    def __init__(
        self,
        table_extractor: Optional[BaseExtractor] = None,
        inline_extractor: Optional[BaseExtractor] = None,
        # ocr_extractor: Optional[BaseExtractor] = None,  # TODO Phase 3
    ):
        self._table = table_extractor or TableExtractor()
        self._inline = inline_extractor or InlineExtractor()
        # self._ocr = ocr_extractor  # TODO Phase 3

    def __call__(self, state: InvoiceRecognitionState) -> dict:
        pdf_doc_dict = state.get("pdf_document")
        if not pdf_doc_dict:
            return {"status": "error", "error": "missing_pdf_document"}

        pdf_doc = PDFDocument(**{k: v for k, v in pdf_doc_dict.items() if k != "pages"})
        from insurance_agent.domain import PDFPage
        pdf_doc.pages = [PDFPage(**p) for p in pdf_doc_dict.get("pages", [])]

        format_hint = state.get("format_hint", "")
        list_pages = state.get("list_pages", [])
        policy_holder = state.get("policy_holder", "")
        insurance_company = state.get("insurance_company", "")

        persons: list[InsuredPerson] = []

        if format_hint == "ocr":
            # TODO Phase 3: 扫描件走视觉模型
            return {
                "status": "error",
                "error": "scanned_pdf_ocr_not_implemented",
                "final_response": '{"error": "扫描件 OCR 待 Phase 3 接入视觉模型"}',
            }

        for page_num in list_pages:
            page = pdf_doc.pages[page_num - 1]
            text = page.text

            if format_hint == "inline":
                persons.extend(self._inline.extract(text, policy_holder, insurance_company))
            else:  # table
                persons.extend(self._table.extract(text, policy_holder, insurance_company))

        # 用整体保险期间兜底缺日期的人员
        overall_start = state.get("working_memory", {}).get("overall_start_date", "")
        overall_end = state.get("working_memory", {}).get("overall_end_date", "")
        for p in persons:
            if not p.start_date:
                p.start_date = overall_start
            if not p.end_date:
                p.end_date = overall_end

        # 构造 ExtractionResult 存回 state
        policy_number = state.get("working_memory", {}).get("policy_number", "")
        result = ExtractionResult(
            file_name=pdf_doc.file_name,
            insurance_company=insurance_company,
            policy_number=policy_number,
            overall_start_date=overall_start,
            overall_end_date=overall_end,
            insured_persons=persons,
            format_used=format_hint,
            extraction_method=("ocr" if format_hint == "ocr" else "text"),
        )

        return {
            "status": "executing",
            "extraction_result": result.to_dict(),
            "tool_results": {
                **state.get("tool_results", {}),
                "personnel_extractor": {
                    "extracted_count": len(persons),
                    "format_hint": format_hint,
                },
            },
        }


def personnel_extractor_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
