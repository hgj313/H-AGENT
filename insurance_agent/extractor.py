"""
Policy Extractor Module

The core extraction engine that combines PDF parsing, format matching,
and LLM-based field extraction to produce structured JSON output.

DDD Layers:
- Protocol: PolicyExtractorProtocol
- Domain: InsuredPerson, ExtractionResult
- Business: PolicyExtractor (orchestrates the extraction pipeline)
"""

import json
import re
import os
from dataclasses import dataclass, field, asdict
from typing import Protocol, Optional, Any

from insurance_agent.pdf_parser import PyMuPDFParser, PDFDocument
from insurance_agent.format_registry import JSONFormatRegistry, CompanyFormat, FieldMapping


# === Domain Models ===

@dataclass
class InsuredPerson:
    """Standard insured person record"""
    name: str = ""               # 姓名
    id_number: str = ""           # 证件号码
    id_type: str = "身份证"       # 证件类型
    company: str = ""             # 所属公司
    start_date: str = ""          # 起始时间
    end_date: str = ""            # 起止时间
    job_title: str = ""           # 岗位名称/工种
    occupation_class: str = ""    # 职业类别
    confidence: float = 0.0       # 提取置信度


@dataclass
class ExtractionResult:
    """Complete extraction result from a policy"""
    file_name: str = ""
    insurance_company: str = ""
    policy_number: str = ""
    overall_start_date: str = ""  # 整体保险起始时间
    overall_end_date: str = ""    # 整体保险终止时间
    insured_persons: list[InsuredPerson] = field(default_factory=list)
    format_used: str = ""         # Format pattern used
    extraction_method: str = ""   # text / ocr / mixed
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        """Convert to stable JSON output"""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_csv_rows(self) -> list[dict]:
        """Convert to flat rows for CSV export"""
        rows = []
        for person in self.insured_persons:
            row = {
                "姓名": person.name,
                "证件号码": person.id_number,
                "证件类型": person.id_type,
                "所属公司": person.company,
                "起始时间": person.start_date or self.overall_start_date,
                "起止时间": person.end_date or self.overall_end_date,
                "岗位名称": person.job_title,
                "保险公司": self.insurance_company,
                "保单号": self.policy_number,
            }
            rows.append(row)
        return rows


# === Protocol ===

class PolicyExtractorProtocol(Protocol):
    """Policy extractor interface"""
    def extract(self, file_path: str) -> ExtractionResult:
        ...


# === Business Layer ===

class PolicyExtractor:
    """Main extraction engine

    Pipeline:
    1. Parse PDF -> PDFDocument
    2. Detect insurance company
    3. Look up format pattern from registry
    4. Extract personnel list using appropriate strategy:
       - text-based extraction (for PDFs with text layer)
       - OCR extraction (for scanned PDFs)
    5. Parse extracted data into structured InsuredPerson records
    6. Validate and produce ExtractionResult
    7. Learn/save format pattern for future use
    """

    def __init__(
        self,
        pdf_parser: PyMuPDFParser = None,
        format_registry: JSONFormatRegistry = None,
        llm_client: Any = None,  # Will be injected later
    ):
        self.pdf_parser = pdf_parser or PyMuPDFParser()
        self.format_registry = format_registry or JSONFormatRegistry()
        self.llm_client = llm_client

    def extract(self, file_path: str) -> ExtractionResult:
        """Full extraction pipeline"""
        result = ExtractionResult(file_name=os.path.basename(file_path))

        # Step 1: Parse PDF
        pdf_doc = self.pdf_parser.parse(file_path)
        result.insurance_company = pdf_doc.insurance_company
        result.extraction_method = "ocr" if pdf_doc.is_scanned else "text"

        # Step 2: Look up format pattern
        company_format = self.format_registry.get_format(pdf_doc.insurance_company)

        # Step 3: Extract policy number, overall dates, and投保人
        self._extract_policy_metadata(pdf_doc, result)
        policy_holder = getattr(result, '_policy_holder', '')

        # Step 4: Find personnel list pages
        list_pages = self._find_personnel_list_pages(pdf_doc, company_format)

        # Step 5: Extract personnel data
        if pdf_doc.is_scanned or not list_pages:
            # Need OCR for scanned PDFs
            if self.llm_client:
                persons = self._extract_via_ocr(pdf_doc, list_pages, company_format)
            else:
                result.errors.append("扫描件PDF需要OCR，但LLM客户端未配置")
                persons = []
        else:
            persons = self._extract_from_text(pdf_doc, list_pages, company_format, policy_holder)

        result.insured_persons = persons

        # Step 6: Fill missing dates from overall period
        self._fill_missing_dates(result)

        # Step 7: Validate
        self._validate_result(result)

        # Step 8: Learn format pattern if new company
        if not company_format and result.insurance_company != "unknown":
            self._learn_format(pdf_doc, result)

        result.format_used = company_format.company_name if company_format else "auto_detected"

        return result

    def _extract_policy_metadata(self, pdf_doc: PDFDocument, result: ExtractionResult):
        """Extract policy number, overall dates, and投保人(company) from all pages"""
        all_text = " ".join(p.text for p in pdf_doc.pages if p.has_meaningful_text)

        # === Extract policy number ===
        policy_patterns = [
            r'保险单号[：:\s]*([A-Za-z0-9]{10,30})',
            r'保单号[：:\s]*([A-Za-z0-9]{10,30})',
            r'保单流水号[：:\s]*([A-Za-z0-9]{10,30})',
        ]
        for pattern in policy_patterns:
            match = re.search(pattern, all_text)
            if match:
                result.policy_number = match.group(1)
                break

        # === Extract投保人/被保险人 company name ===
        company_patterns = [
            r'投保人名称[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))',
            r'投保人/被保险人[名称信息]*[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))',
            r'名称[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))',
            r'被保险人名称[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))',
        ]
        for pattern in company_patterns:
            match = re.search(pattern, all_text)
            if match:
                # Store as metadata - will be used for per-person company field
                result._policy_holder = match.group(1).strip()
                break

        # === Extract overall insurance dates ===
        date_patterns = [
            # Liberty: 自2026年06月17日0时起至2026年09月16日24时止
            r'自(\d{4})年(\d{2})月(\d{2})日[0时\d\s]*起[，]?\s*至(\d{4})年(\d{2})月(\d{2})日[\d\s时]*止',
            # CPIC: 自2026年06月24日 00时00分00秒起至2026年09月24日 00时00分00秒止
            r'自(\d{4})[年\-](\d{2})[月\-](\d{2})[\s日]*[\d时:分秒]*起[，]?\s*至(\d{4})[年\-](\d{2})[月\-](\d{2})[\s日]*[\d时:分秒]*止',
            # Generic fallback
            r'保险期间[：:\s]*自(\d{4})[年\-](\d{2})[月\-](\d{2})[\s日\d:]*至(\d{4})[年\-](\d{2})[月\-](\d{2})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, all_text)
            if match:
                groups = match.groups()
                result.overall_start_date = f"{groups[0]}-{groups[1]}-{groups[2]}"
                result.overall_end_date = f"{groups[3]}-{groups[4]}-{groups[5]}"
                break

    def _find_personnel_list_pages(
        self, pdf_doc: PDFDocument, company_format: Optional[CompanyFormat]
    ) -> list[int]:
        """Find pages containing personnel lists - use precise markers only"""
        # Precise markers that indicate a personnel/employee list
        primary_markers = ["人员清单", "雇员清单", "被保险人清单", "雇员清单"]
        secondary_markers = ["雇员姓名：", "雇员姓名:"]  # Inline format (批单)

        # Add company-specific markers
        if company_format:
            primary_markers.append(company_format.list_page_marker)
            primary_markers.append(company_format.list_title_pattern)

        list_pages = []
        for page in pdf_doc.pages:
            if not page.has_meaningful_text:
                continue

            # Check primary markers (dedicated list pages)
            for marker in primary_markers:
                if marker in page.text:
                    list_pages.append(page.page_number)
                    break

            # Check secondary markers (inline format like 批单)
            if page.page_number not in list_pages:
                for marker in secondary_markers:
                    if marker in page.text:
                        list_pages.append(page.page_number)
                        break

        return list_pages

    def _extract_from_text(
        self,
        pdf_doc: PDFDocument,
        list_pages: list[int],
        company_format: Optional[CompanyFormat],
        policy_holder: str = ""
    ) -> list[InsuredPerson]:
        """Extract personnel data from text layer using company-specific strategies"""
        persons = []

        # If policy_holder not provided, search all pages for it
        if not policy_holder:
            all_text = " ".join(p.text for p in pdf_doc.pages if p.has_meaningful_text)
            company_patterns = [
                r'投保人名称[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))',
                r'名称[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))\s',
                r'投保人/被保险人[名称信息]*[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))',
            ]
            for pattern in company_patterns:
                match = re.search(pattern, all_text)
                if match:
                    policy_holder = match.group(1).strip()
                    break

        for page_num in list_pages:
            page = pdf_doc.pages[page_num - 1]
            text = page.text

            # Strategy 1: Inline format (批单 - Liberty Insurance endorsement)
            inline_persons = self._parse_inline_text(text, policy_holder)
            if inline_persons:
                persons.extend(inline_persons)
                continue

            # Strategy 2: Table format - parse structured table data
            table_persons = self._parse_table_text_v2(text, pdf_doc.insurance_company, policy_holder)
            if table_persons:
                persons.extend(table_persons)
                continue

        return persons

    def _parse_table_text_v2(
        self, text: str, insurance_company: str, policy_holder: str
    ) -> list[InsuredPerson]:
        """Parse personnel data from table-formatted text (v2 - precise)

        Key improvement: Only accept ID numbers that look like Chinese citizen IDs:
        - 18 digits (17 digits + X/x)
        - Start with area code prefix (valid Chinese province codes)
        - NOT policy numbers, clause numbers, or other 18-digit strings
        """
        persons = []

        # === Step 1: Find the list section in the page ===
        # The personnel list starts after "人员清单" or "雇员清单" marker
        list_markers = ["人员清单", "雇员清单", "被保险人清单"]
        list_start_idx = 0
        for marker in list_markers:
            idx = text.find(marker)
            if idx >= 0:
                list_start_idx = idx
                break

        # If no marker found, use the entire text
        list_text = text[list_start_idx:] if list_start_idx > 0 else text

        # === Step 2: Find valid Chinese ID numbers ===
        # Chinese ID format: area code (6 digits) + birth date (8 digits: YYYYMMDD)
        #   + sequence (3 digits) + check digit (1 digit or X)
        # Area codes must start with valid province prefixes (11-65, 71, 81, 82, 91)
        # Birth year must be reasonable (1940-2026), month (01-12), day (01-31)

        # Valid first-2-digit area code prefixes for Chinese provinces
        VALID_AREA_PREFIXES = {
            '11','12','13','14','15',  #华北: 北京/天津/河北/山西/内蒙古
            '21','22','23',            #东北: 辽宁/吉林/黑龙江
            '31','32','33','34','35','36','37',  #华东: 上海/江苏/浙江/安徽/福建/江西/山东
            '41','42','43','44','45','46',  #华中南: 河南/湖北/湖南/广东/广西/海南
            '50','51','52','53','54',  #西南: 重庆/四川/贵州/云南/西藏
            '61','62','63','64','65',  #西北: 陕西/甘肃/青海/宁夏/新疆
            '71',                      #台湾
            '81','82',                 #香港/澳门
            '91',                      #国外
        }

        id_pattern = re.compile(
            r'(\d{2}\d{4})(19[4-9]\d|20[0-2]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]'
        )

        id_matches = list(id_pattern.finditer(list_text))

        if not id_matches:
            return persons

        # === Step 3: For each valid ID, extract surrounding context ===
        # The text extracted by pymupdf from tables flows in reading order.
        # Fields near the ID number in the text belong to the same row.

        for match in id_matches:
            id_number = match.group(0).upper()  # Normalize X to uppercase
            # Validate: area code prefix must be a valid Chinese province
            area_prefix = id_number[:2]
            if area_prefix not in VALID_AREA_PREFIXES:
                continue

            # Validate: birth date should be plausible
            birth_year = int(match.group(2))
            birth_month = int(match.group(3))
            birth_day = int(match.group(4))

            # Skip if birth date is implausible
            if birth_year < 1940 or birth_year > 2026:
                continue

            person = InsuredPerson(
                id_number=id_number,
                confidence=0.85,
            )

            # === Extract name: Chinese characters just before the ID number ===
            # In pymupdf text extraction from tables, the name field appears
            # right before the ID number in the text stream
            pre_text = list_text[:match.start()]
            # Find the last few Chinese character sequences before the ID
            # Typically 2-4 characters for a Chinese name
            name_candidates = re.findall(r'[\u4e00-\u9fff]{2,4}', pre_text[-100:] if len(pre_text) > 100 else pre_text)

            # Filter out known non-name words
            NON_NAME_WORDS = {
                "身份证", "证件", "雇员", "序号", "姓名", "性别", "年龄",
                "职业", "等级", "参保", "计划", "用工", "单位", "岗位",
                "起期", "止期", "道路", "绿化", "工", "类", "号",
                "保单", "保险", "清单", "人员", "雇员", "说明",
                "销售", "渠道", "代理", "经纪", "广东", "美保",
                "签章", "系统", "打印", "盖章", "投保",
                "安装", "结构", "钢", "劳务", "建筑", "工程",
                "装饰", "有限", "公司", "责任", "条款",
                "普通", "绿化工", "道路绿化工",
                "钢结构安装工", "高处", "作业",
                "普通道路",
            }
            valid_names = [n for n in name_candidates if n not in NON_NAME_WORDS and len(n) >= 2]

            if valid_names:
                person.name = valid_names[-1]  # Last valid name before ID

            # === Extract dates near the ID number ===
            # Look for date patterns in the context around the ID
            post_text = list_text[match.end():match.end() + 300]
            date_pattern = re.compile(r'(\d{4})-(\d{2})-(\d{2})\s*\d{2}:\d{2}:\d{2}')
            dates = date_pattern.findall(post_text)

            if len(dates) >= 2:
                # First date is start, second is end
                person.start_date = f"{dates[0][0]}-{dates[0][1]}-{dates[0][2]}"
                person.end_date = f"{dates[1][0]}-{dates[1][1]}-{dates[1][2]}"
            elif len(dates) == 1:
                # Only one date found - might be start or end
                person.start_date = f"{dates[0][0]}-{dates[0][1]}-{dates[0][2]}"

            # === Extract company/用工单位 ===
            # Look for用工单位 in the same context - capture full company names
            company_in_context = re.findall(
                r'([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))',
                post_text[:200]
            )
            # Also check the full page for用工单位 pattern
            if not company_in_context:
                company_match = re.search(r'用工单位[\s]*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))', list_text)
                if company_match:
                    company_in_context = [company_match.group(1)]

            if company_in_context:
                person.company = company_in_context[0]
            elif policy_holder:
                person.company = policy_holder

            # === Extract job title ===
            # Common patterns for occupation/job in insurance tables
            job_match = re.search(
                r'(?:职业名称|岗位名称|工种描述)[\s]*([\u4e00-\u9fff]+(?:工|员|师|者|人))',
                list_text
            )
            if not job_match:
                # Try finding job title near the ID number in post_text
                job_match = re.search(
                    r'([\u4e00-\u9fff]{2,8}(?:工|员|师|者))',
                    post_text[:200]
                )
            if job_match:
                person.job_title = job_match.group(1)

            persons.append(person)

        return persons

    def _parse_inline_text(
        self, text: str, policy_holder: str = ""
    ) -> list[InsuredPerson]:
        """Parse inline-formatted personnel data (e.g., 批单 format)

        Example format (Liberty Insurance 批单):
        雇员姓名：张绍应，证件号：510223196903036833，方案序号：5，工种描述：砌筑工，
        用工单位：重庆选鹏建筑工程有限公司，保费计(CNY)：464.00；
        """
        persons = []

        # Pattern: 雇员姓名：XXX，证件号：XXX...用工单位：XXX...
        # Note: name may contain trailing comma, handle it
        inline_pattern = re.compile(
            r'雇员姓名[：:]\s*([\u4e00-\u9fff]{2,4})\s*[，,]\s*'
            r'证件号[：:]\s*(\d{17}[\dXx])\s*[，,]'
        )

        matches = inline_pattern.findall(text)
        for name, id_number in matches:
            person = InsuredPerson(
                name=name,
                id_number=id_number.upper(),
                confidence=0.9,
            )

            # Extract per-person用工单位 from the same line
            # Find the full line containing this person
            line_start = text.find(f"雇员姓名：{name}") or text.find(f"雇员姓名:{name}")
            if line_start >= 0:
                line_end = text.find('；', line_start) or text.find('。', line_start)
                line = text[line_start:min(line_end + 1, line_start + 500) if line_end > line_start else line_start + 500]

                # Extract用工单位
                company_match = re.search(r'用工单位[：:]\s*([\u4e00-\u9fff]+(?:有限公司|集团公司|股份有限公司|公司))', line)
                if company_match:
                    person.company = company_match.group(1)
                elif policy_holder:
                    person.company = policy_holder

                # Extract工种描述
                job_match = re.search(r'工种描述[：:]\s*([\u4e00-\u9fff]+)', line)
                if job_match:
                    person.job_title = job_match.group(1)

            persons.append(person)

        # If inline extraction found nothing, return empty (don't fall back to table parsing)
        return persons

    def _extract_via_ocr(
        self,
        pdf_doc: PDFDocument,
        list_pages: list[int],
        company_format: Optional[CompanyFormat]
    ) -> list[InsuredPerson]:
        """Extract personnel data using vision model OCR

        For scanned PDFs, convert pages to images and send to vision model.
        """
        if not self.llm_client:
            return []

        # Determine which pages need OCR
        pages_to_ocr = list_pages if list_pages else range(1, pdf_doc.total_pages + 1)

        persons = []
        for page_num in pages_to_ocr:
            img_base64 = self.pdf_parser.get_page_image(pdf_doc, page_num)
            # Call vision model with structured prompt
            ocr_result = self._call_vision_model(img_base64)
            if ocr_result:
                persons.extend(ocr_result)

        return persons

    def _call_vision_model(self, img_base64: str) -> list[InsuredPerson]:
        """Call vision model for OCR extraction

        This method requires an LLM client to be configured.
        The prompt is designed for stable JSON output.
        """
        if not self.llm_client:
            return []

        # This will be implemented with the actual LLM client
        # For now, return empty - the LLM integration will be added in Phase 3
        prompt = self._build_ocr_prompt()
        # result = self.llm_client.invoke(prompt, image=img_base64)
        # return self._parse_ocr_json_result(result)
        return []

    def _build_ocr_prompt(self) -> str:
        """Build structured prompt for vision model OCR"""
        return """
你是一个专业的保险单识别助手。请仔细分析这张保险单图片，提取被保人员清单信息。

## 必须提取的字段

请按照以下 JSON Schema 返回结果：

```json
{
  "insurance_company": "保险公司名称",
  "policy_number": "保单号",
  "overall_start_date": "整体保险起始日期（YYYY-MM-DD格式）",
  "overall_end_date": "整体保险终止日期（YYYY-MM-DD格式）",
  "insured_persons": [
    {
      "name": "姓名",
      "id_type": "证件类型",
      "id_number": "证件号码（18位）",
      "company": "所属公司/用工单位",
      "start_date": "起始时间（YYYY-MM-DD格式，如有）",
      "end_date": "起止时间（YYYY-MM-DD格式，如有）",
      "job_title": "岗位名称/工种"
    }
  ]
}
```

## 输出要求

1. 必须返回合法 JSON，可以被 json.loads() 解析
2. 证件号码必须是完整的18位数字（最后一位可能是X）
3. 如果保单中有每个人员的起止日期，请分别提取；如果只有整体保险期限，则每个人的起止日期填写整体期限
4. 无法识别的字段返回空字符串 ""
5. 不要返回 Markdown 代码块标记，直接返回 JSON
6. 回答必须是中文，键名必须是英文

请分析图片并以 JSON 格式返回结果。
"""

    def _fill_missing_dates(self, result: ExtractionResult):
        """Fill missing per-person dates with overall insurance period"""
        if not result.overall_start_date and not result.overall_end_date:
            return

        for person in result.insured_persons:
            if not person.start_date:
                person.start_date = result.overall_start_date
            if not person.end_date:
                person.end_date = result.overall_end_date

    def _validate_result(self, result: ExtractionResult):
        """Validate extraction result"""
        for person in result.insured_persons:
            # Validate ID number format
            if person.id_number:
                id_pattern = re.compile(r'^\d{17}[\dXx]$')
                if not id_pattern.match(person.id_number):
                    result.warnings.append(
                        f"证件号码格式异常: {person.name} - {person.id_number}"
                    )

            # Check for missing required fields
            if not person.name:
                result.warnings.append(f"缺少姓名: ID={person.id_number}")
            if not person.id_number:
                result.warnings.append(f"缺少证件号码: {person.name}")

    def _learn_format(self, pdf_doc: PDFDocument, result: ExtractionResult):
        """Learn and save format pattern for a newly encountered insurance company"""
        # Find the personnel list page
        list_pages = self._find_personnel_list_pages(pdf_doc, None)

        if not list_pages:
            return

        # Analyze the first list page
        page = pdf_doc.pages[list_pages[0] - 1]
        text = page.text

        # Detect field names from the table headers
        field_names = self._detect_field_names(text)

        # Determine if per-person dates exist
        has_per_person_dates = any(
            "起期" in text or "止期" in text or
            re.search(r'\d{4}\-\d{2}\-\d{2}', text)
            for p in [page]
        )

        # Detect table type
        table_type = "table"  # Default
        if "雇员姓名：" in text or "证件号：" in text:
            table_type = "inline"

        # Build format pattern
        mappings = []
        standard_to_company = {
            "name": ["雇员姓名", "姓名"],
            "id_type": ["证件类型"],
            "id_number": ["证件号", "证件号码"],
            "company": ["用工单位", "所属公司"],
            "start_date": ["起期", "起始时间"],
            "end_date": ["止期", "起止时间"],
            "job_title": ["职业名称", "岗位名称", "工种描述"],
            "occupation_class": ["职业", "职业等级", "职业类别"],
        }

        for standard_field, possible_names in standard_to_company.items():
            for company_field in possible_names:
                if company_field in field_names:
                    mappings.append(FieldMapping(
                        standard_field=standard_field,
                        company_field=company_field,
                        field_type="date" if standard_field in ("start_date", "end_date") else "text",
                    ))
                    break

        # Detect list title
        title_patterns = ["人员清单", "雇员清单", "被保险人清单"]
        list_title = next((p for p in title_patterns if p in text), "清单")

        company_format = CompanyFormat(
            company_name=result.insurance_company,
            list_title_pattern=list_title,
            list_page_marker=list_title,
            field_mappings=mappings,
            table_type=table_type,
            has_per_person_dates=has_per_person_dates,
            overall_date_pattern=r'自\d{4}年\d{2}月\d{2}日.*至\d{4}年\d{2}月\d{2}日',
            confidence=0.7,
            notes=f"Auto-detected from {result.file_name}",
        )

        self.format_registry.save_format(company_format)

    def _detect_field_names(self, text: str) -> list[str]:
        """Detect field/column names from table text"""
        # Common field name patterns
        known_fields = [
            "序号", "雇员姓名", "姓名", "证件类型", "证件号", "证件号码",
            "性别", "年龄", "职业名称", "岗位名称", "工种描述",
            "职业", "等级", "参保", "计划", "用工单位",
            "起期", "止期", "保费",
        ]

        found = [f for f in known_fields if f in text]
        return found


# === Helper: JSON Stable Output ===

def parse_json_with_fallback(result: str) -> dict:
    """Attempt multiple methods to parse JSON from LLM output"""
    # Method 1: Direct parse
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        pass

    # Method 2: Extract from Markdown code block
    match = re.search(r'```json\n(.*?)\n```', result, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Method 3: Extract outermost {}
    match = re.search(r'\{.*\}', result, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Method 4: Fallback
    return {"error": "JSON解析失败", "raw": result[:500]}
