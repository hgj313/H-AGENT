"""Node 3: PersonnelExtractorNode

职责：
- 根据 format_hint 选择对应 Extractor
- 从 list_pages 提取 InsuredPerson
- 缺日期时用整体保险期间兜底
- format_hint == "ocr" 时走 OCRExtractor（Phase 3）

DI：所有 Extractor 通过构造器注入。
"""

from typing import Optional
import logging
from insurance_agent.domain import PDFDocument, InsuredPerson, ExtractionResult
from insurance_agent.extractors import (
    BaseExtractor, TableExtractor, InlineExtractor, IndividualExtractor,
    BlockKVExtractor, OCRExtractor,  # 2026-09-17 新增 BlockKVExtractor
)
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState


logger = logging.getLogger(__name__)


class PersonnelExtractorNode:
    """人员提取节点

    DI：注入四种 Extractor（table / inline / individual / block_kv / ocr）。
    """

    def __init__(
        self,
        table_extractor: Optional[BaseExtractor] = None,
        inline_extractor: Optional[BaseExtractor] = None,
        individual_extractor: Optional[BaseExtractor] = None,
        block_kv_extractor: Optional[BaseExtractor] = None,
        ocr_extractor: Optional[BaseExtractor] = None,
    ):
        self._table = table_extractor or TableExtractor()
        self._inline = inline_extractor or InlineExtractor()
        self._individual = individual_extractor or IndividualExtractor()
        self._block_kv = block_kv_extractor or BlockKVExtractor()  # 2026-09-17 新增
        self._ocr = ocr_extractor  # OCR 需要 LLM，默认不注入

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
        # 2026-11-13 新增：扫描件版面元数据（保单号/保险期间）
        # 扫描件没有文字层 → metadata_extractor 取不到保单号与保险期间 →
        # 人员日期全空、policy_number 全空 → 无法关联主保单回填。
        # 这里对首页做一次版面元数据 OCR，补上这块缺失的信息。
        ocr_meta: dict = {}

        if format_hint == "no_list":
            # 不记名投保（灵工版等）：只有总投保员工人数，无法逐人提取
            # 走 OCR 会浪费时间和 LLM 费用，且扫描件上无清单也无意义
            # 直接返回空，由前端展示"总投保 N 人，不记名"
            persons = []

        elif format_hint == "ocr":
            # Phase 3: 扫描件走视觉模型 OCR
            if not self._ocr:
                return {
                    "status": "error",
                    "error": "ocr_extractor_not_injected",
                    "final_response": '{"error": "OCR 提取器未注入 LLM 客户端"}',
                }
            page_images = state.get("page_images", [])
            # 2026-11-13：先读版面元数据（首页通常带保单号与保险期间）
            # ⚠️ 这里刻意不吞异常：元数据 OCR 失败不应阻断人员提取，
            #    失败时降级为「无元数据」，人员仍照常提取（日期留空）。
            # max_pages=4：页眉每页都印着保单号 → 跨页投票交叉验证，
            # 避免视觉模型把长数字串读错一位（实测低清图会多插 0）。
            try:
                ocr_meta = self._ocr.extract_overall_metadata(
                    page_images=page_images,
                    max_pages=4,
                ) or {}
            except Exception as e:
                logger.warning("扫描件版面元数据 OCR 失败（不影响人员提取）: %s", e)
                ocr_meta = {}
            try:
                persons = self._ocr.extract(
                    policy_holder=policy_holder,
                    insurance_company=insurance_company,
                    page_images=page_images,
                )
            except Exception as e:
                # 失败透传：直接抛异常，不兜底
                raise RuntimeError(f"OCR 提取失败: {e}") from e

            # 2026-11-13：版面元数据兜底保险公司 / 投保人
            # （扫描件下文字层拿不到，只能靠首页 OCR；已有值优先，不覆盖）
            if ocr_meta:
                if insurance_company in ("", "unknown") and ocr_meta.get("insurance_company"):
                    insurance_company = ocr_meta["insurance_company"]
                if not policy_holder and ocr_meta.get("policy_holder"):
                    policy_holder = ocr_meta["policy_holder"]

        else:
            # 文字层：table / inline / individual 格式
            # 2026-10-08 修复：当 format_hint 是 inline 但 list_pages 为空时（如阳光批单
            # 《变更被保人》：单页 PDF 含 inline marker 但无传统清单页），需扫描所有页
            # 找到含 inline marker 的页面提取，避免 0 人提取。
            if not list_pages and format_hint == "inline":
                from insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node import (
                    _INLINE_MARKERS,
                )
                pages_to_extract = [
                    p.page_number for p in pdf_doc.pages
                    if any(m in p.text for m in _INLINE_MARKERS)
                ]
                if not pages_to_extract:
                    # 兜底：扫所有页
                    pages_to_extract = [p.page_number for p in pdf_doc.pages]
            else:
                pages_to_extract = list_pages

            for page_num in pages_to_extract:
                page = pdf_doc.pages[page_num - 1]
                text = page.text

                if format_hint == "inline":
                    persons.extend(self._inline.extract(text, policy_holder, insurance_company))
                elif format_hint == "individual":
                    persons.extend(self._individual.extract(text, policy_holder, insurance_company))
                elif format_hint == "block_kv":
                    persons.extend(self._block_kv.extract(text, policy_holder, insurance_company))
                else:  # table（默认）
                    persons.extend(self._table.extract(text, policy_holder, insurance_company))

        # 用整体保险期间兜底缺日期的人员
        # 2026-11-13：扫描件下 working_memory 里的整体期间来自文字层 → 为空，
        #   用 OCR 读回的版面元数据兜底（已有值优先，不覆盖文字层结果）。
        overall_start = (
            state.get("working_memory", {}).get("overall_start_date", "")
            or ocr_meta.get("overall_start_date", "")
        )
        overall_end = (
            state.get("working_memory", {}).get("overall_end_date", "")
            or ocr_meta.get("overall_end_date", "")
        )
        for p in persons:
            if not p.start_date:
                p.start_date = overall_start
            if not p.end_date:
                p.end_date = overall_end

        # 构造 ExtractionResult 存回 state
        policy_number = (
            state.get("working_memory", {}).get("policy_number", "")
            or ocr_meta.get("policy_number", "")
        )
        # 2026-09-21 增强：读 batch/main policy_number + policy_type，供下游入库用
        batch_policy_number = state.get("working_memory", {}).get("batch_policy_number", "")
        main_policy_number = state.get("working_memory", {}).get("main_policy_number", "")
        policy_type = state.get("working_memory", {}).get("policy_type", "")
        # 2026-09-16 修复：从 working_memory 读取批单生效日，避免 _persist_policy_result 减保时
        # 降级用 overall_start（主保单起期）兜底。谭建芬事件：end_date=主保单起期(2026-06-17)，
        # 应是批单004生效日(2026-09-13)。
        endorsement_effective_date = state.get("working_memory", {}).get("endorsement_effective_date", "")
        result = ExtractionResult(
            file_name=pdf_doc.file_name,
            insurance_company=insurance_company,
            policy_number=policy_number,
            batch_policy_number=batch_policy_number,
            main_policy_number=main_policy_number,
            policy_type=policy_type,
            overall_start_date=overall_start,
            overall_end_date=overall_end,
            endorsement_effective_date=endorsement_effective_date,
            insured_persons=persons,
            format_used=format_hint,
            extraction_method=("ocr" if format_hint == "ocr" else "text"),
        )

        return {
            "status": "executing",
            "extraction_result": result.to_dict(),
            # 2026-11-13：把扫描件 OCR 读回的版面元数据并回 working_memory，
            #   让下游 validator（主保单关联）与入库环节能拿到保单号与整体期间。
            "working_memory": {
                **state.get("working_memory", {}),
                "policy_number": policy_number,
                "overall_start_date": overall_start,
                "overall_end_date": overall_end,
                **({"insurance_company": insurance_company} if insurance_company else {}),
                **({"policy_holder": policy_holder} if policy_holder else {}),
            },
            "tool_results": {
                **state.get("tool_results", {}),
                "personnel_extractor": {
                    "extracted_count": len(persons),
                    "format_hint": format_hint,
                    **({"ocr_metadata": ocr_meta} if ocr_meta else {}),
                },
            },
        }


def personnel_extractor_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
