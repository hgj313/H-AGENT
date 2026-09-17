"""Node 2: MetadataExtractorNode

职责：
- 从 PDF 全文档文字中提取保单号、整体保险期间、投保人公司名
- 定位人员清单所在页
- 决策 format_hint（table / inline / ocr）
"""

import logging
import re
from insurance_agent.domain import PDFDocument
from insurance_agent.tools import (
    extract_company_after_label,
    extract_overall_insurance_period,
    extract_company_name,
    detect_insurance_company_by_policy_number,
)
from insurance_agent.agents.invoice_recognition.states.inv_state import InvoiceRecognitionState

logger = logging.getLogger(__name__)


# 人员清单页定位标记
_LIST_MARKERS = [
    "人员清单", "雇员清单", "雇员人名清单", "人名清单",
    "被保险人清单", "员工清单", "被保险人名单",
    # 雇主责任险电子保单（安诚保险等）：雇员信息表
    "雇员信息", "雇员名单", "员工信息",
    # 批单中的雇员变动清单
    "雇员变动清单", "人员变动清单", "变动清单", "批改清单",
    "新增被保险人清单", "减少被保险人清单", "被保险人变动",
    # 众安在线等新格式：人员名单表 / 雇员明细表 / 雇员信息表 / 人员信息表
    "人员名单", "雇员明细表", "雇员明细", "人员明细",
    "雇员信息表", "人员信息表", "人员清单表", "雇员清单表",
]
# 行内格式标记
_INLINE_MARKERS = ["雇员姓名：", "雇员姓名:", "雇员姓名：", "雇员姓名:", "替换为人员"]
# 个人保单格式标记（被保险人信息以键值对形式内嵌）
_INDIVIDUAL_MARKERS = ["被保险人信息", "被保人信息"]
# 不记名投保保单特征（灵工版等 — 只投总人数，不逐人记名 → 无清单）
_UNLISTED_MARKERS = ["是否记名投保", "总投保员工人数", "不记名投保", "灵工版", "灵工雇主"]
# 块状键值对清单标记（2026-09-17 新增：中国人寿"在保名单"绿洲团体意外险等）
# 特征：抬头含"有效被保险人清单"+"汇交号/保险合同号"+每人有"生效日期/终止日期"
_BLOCK_KV_MARKERS = [
    "有效被保险人清单",   # 中国人寿绿洲团体意外险典型特征
    "被保人顺序号",         # 块状格式特征
    "要约状态",             # 块状格式特征
    "汇交号",               # 中国人寿绿洲团体意外险保单号前缀
]

# 批单生效日期：自 2026年09月04日 零时起生效
# 提取批单整体生效日（单点日期），用于减保记录的 end_date 补全
_ENDORSEMENT_EFFECTIVE_PATTERN = re.compile(
    r"自\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*零时起\s*生效"
)


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
        fname_for_extract = state.get("file_path", "")
        policy_number = self._extract_policy_number(all_text, file_name=fname_for_extract)

        # 1.5 号段兜底（2026-09-16 新增）：保单号前缀是承保机构发行的硬证据，
        # 比 PDF 文本中关键词匹配更可靠（段小平事件：华安批单088 PDF 提到"黄河"
        # 被错识别为黄河财险，但保单号 613010104 是华安号段）。
        insurance_company_override = detect_insurance_company_by_policy_number(policy_number)
        if insurance_company_override:
            logger.info(
                "保单号 %s 号段匹配保险公司 %s，覆写文本检测结果",
                policy_number, insurance_company_override,
            )

        # 2. 整体保险期间
        overall_start, overall_end = extract_overall_insurance_period(all_text)

        # 2.5 批单生效日期（2026-09-15 新增）
        # 批单的"自 X年Y月Z日 零时起生效"是单点日期，extract_overall_insurance_period 的
        # "起至...止"模式无法匹配。提取后用于减保记录的 end_date 补全（避免错填为主保单止期）。
        endorsement_effective_date = ""
        m_eff = _ENDORSEMENT_EFFECTIVE_PATTERN.search(all_text)
        if m_eff:
            year, month, day = m_eff.group(1), m_eff.group(2), m_eff.group(3)
            endorsement_effective_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        # 3. 投保人公司名
        policy_holder = extract_company_after_label(all_text) or extract_company_name(all_text) or ""

        # 4. 人员清单页定位
        list_pages = self._find_list_pages(pdf_doc)

        # 5. 决策 format_hint
        # 注意：文件名含"投保单"不能直接判定为无清单。
        #   例：某保险公司把"保险单"文件命名为"XXX投保单.pdf"，实际含 保险单号 + 人员清单。
        #   真正的 投保申请书（仅条款）特征：无 保险单号 且 无 人员清单页。
        #   因此"投保单"文件名仅作为弱信号，且需 保险单号/清单页 都不存在时才判 no_list。
        fname = state.get("file_path", "")
        is_toubiaodan_file = "投保单" in fname

        if list_pages:
            # 有人员清单页 → 真实保单，优先按清单格式识别
            if any(marker in all_text for marker in _INLINE_MARKERS):
                format_hint = "inline"
            elif any(marker in all_text for marker in _BLOCK_KV_MARKERS):
                # 块状键值对清单（2026-09-17 新增：中国人寿"在保名单"绿洲团体意外险等）
                format_hint = "block_kv"
            elif self._is_individual_policy(all_text):
                format_hint = "individual"
                list_pages = self._find_individual_pages(pdf_doc) or list_pages
            else:
                format_hint = "table"
        elif state.get("is_scanned"):
            format_hint = "ocr"
        elif is_toubiaodan_file and not policy_number:
            # 文件名含"投保单"且确无保单号/清单 → 投保申请书（仅条款），无人员清单
            format_hint = "no_list"
        elif self._is_unlisted_policy(all_text):
            # 不记名投保（如灵工版）：只有总人数，没有人员清单
            format_hint = "no_list"
        elif self._is_individual_policy(all_text):
            format_hint = "individual"
            list_pages = self._find_individual_pages(pdf_doc)
        else:
            format_hint = "ocr"  # 兜底走 OCR

        return {
            "status": "executing",
            "policy_holder": policy_holder,
            "list_pages": list_pages,
            "format_hint": format_hint,
            # 2026-09-16 新增：号段映射覆盖 insurance_company（华安批单088 类场景防御）
            **({"insurance_company": insurance_company_override} if insurance_company_override else {}),
            "tool_results": {
                **state.get("tool_results", {}),
                "metadata_extractor": {
                    "policy_number": policy_number,
                    "overall_start_date": overall_start,
                    "overall_end_date": overall_end,
                    "endorsement_effective_date": endorsement_effective_date,
                    "policy_holder": policy_holder,
                    "list_pages": list_pages,
                    "format_hint": format_hint,
                    "insurance_company_override": insurance_company_override,
                },
            },
            "working_memory": {
                **state.get("working_memory", {}),
                "policy_number": policy_number,
                "overall_start_date": overall_start,
                "overall_end_date": overall_end,
                "endorsement_effective_date": endorsement_effective_date,
            },
        }

    @staticmethod
    def _extract_policy_number(text: str, file_name: str = "") -> str:
        """从 PDF 全文中提取"保单单号"（系统唯一编号）。

        优先级（2026-09-16 增强）：批单号(若批单文件) > 保单单号 > 保单号 > 保单流水号

        背景（2026-09-16 修复）：利宝批单 PDF 中同时含：
        - "保险单号 8116013100260072423000"（主保单号，81开头）
        - "批单号 7116013100260072423004"（批单号，71开头）
        旧逻辑总是先匹配"保险单号" → result_dict["policy_number"] 变成主保单号 → 入库后
        policy_number 字段错填为 81 主保单号（63 条批单记录全部中招）。

        新逻辑（2026-09-16 v2）：如果是批单文件（文件名含"批单"），优先匹配"批单号"。
        若 PDF 文本仍未匹配到，fallback 用 parse_policy_filename 从文件名解析（处理 BD 格式）。
        否则按原优先级。

        BD 格式陷阱：万年县盛美 BD 格式 PDF 文本中没有"批单号"字样，只有"保险单号"+主保单号。
        但文件名 `万年县盛美建筑工程有限公司_7116013100260112989001_BD.pdf` 含完整批单号
        → 必须用 filename_parser 兜底，否则 policy_number 永远错填为 81 主保单号。
        """
        from insurance_agent.tools.filename_parser import parse_policy_filename

        is_endorsement = "批单" in file_name or "BD" in file_name.upper()

        if is_endorsement:
            # 批单：优先匹配"批单号"
            patterns = [
                r"批单号[：:\s]*([A-Z0-9]{16,30})",                  # 1. 利宝等：批单号
                r"保险单号[：:\s]*([A-Z0-9]{16,30})",                # 2. fallback 主保单号
                r"保险单或凭证号次[\s\S]{0,30}?([A-Z0-9]{16,30})",  # 3. 太保
                r"保单号[：:\s]*([A-Z0-9]{16,30})",
                r"保单流水号[\s\S]{0,30}?([A-Z0-9]{16,30})",
            ]
        else:
            # 主保单：原优先级
            patterns = [
                r"保险单或凭证号次[\s\S]{0,30}?([A-Z0-9]{16,30})",  # 1. 太保：保单单号（系统唯一编号），容许中间夹 1-2 行
                r"凭证号次[\s\S]{0,30}?([A-Z0-9]{16,30})",            # 2. 太保：简称
                r"汇交号[/／\s]*保险合同号[：:\s]*([A-Z0-9]{16,30})", # 2.5 中国人寿绿洲团体意外险"在保名单"汇交号（2026-09-17 新增）
                r"保险合同号[：:\s]*([A-Z0-9]{16,30})",                # 2.6 中国人寿"汇交号/保险合同号"另一形式
                r"保险单号[：:\s]*([A-Z0-9]{16,30})",                # 3. 利宝等：主保单号
                r"保单号[：:\s]*([A-Z0-9]{16,30})",                  # 4. 利宝等：主保单号
                r"保单流水号[\s\S]{0,30}?([A-Z0-9]{16,30})",          # 5. 太保：保单内部流水号（fallback）
            ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                pn = m.group(1)
                # 2026-09-16 v2 兜底：批单文件若仍拿到 81 开头主保单号，
                # 说明 PDF 文本无"批单号"标签（BD 格式万年县盛美等），用文件名保单号覆盖
                if is_endorsement and pn.startswith("8"):
                    fname_info = parse_policy_filename(file_name)
                    if fname_info.policy_number and fname_info.policy_number.startswith("7"):
                        return fname_info.policy_number
                return pn

        # 所有正则都没匹配上 → 兜底用文件名解析
        if is_endorsement:
            fname_info = parse_policy_filename(file_name)
            if fname_info.policy_number:
                return fname_info.policy_number

        return ""

    @staticmethod
    def _is_clause_page(text: str) -> bool:
        """判断是否为条款页（含"第X条"/"第X部分"/"附录："等章节术语）。

        注意：不能仅用"条款"一词判定，因为保单明细表、特别约定等页面也常含
        "本保险合同条款"等上下文文字，会误伤真实清单页。
        """
        # 章节术语：精确匹配条款典型结构
        if any(s in text for s in ['第一条', '第二条', '第三条', '第四条', '第五条']):
            return True
        if any(p in text for p in [
            '第一部分', '第二部分', '第三部分', '第四部分', '第五部分',
            '第六部分', '第七部分', '第八部分', '第九部分', '第十部分',
            '第十一部分', '第十二部分',
        ]):
            return True
        if '附录：' in text or ('附录' in text and '赔偿限额比例表' in text):
            return True
        # 职业分类表（众安等）：含"职业类别"+"大类行业"+"小类行业" 三大特征
        if '大类行业' in text and '小类行业' in text and '职业类别' in text:
            return True
        # 条款注册号段（"注册号：C000179309120260..."）
        if '注册号：' in text and ('条款' in text or '附加险' in text or '附加条款' in text):
            return True
        # 责任免除、释义、赔偿处理等条款章节典型关键词
        if '责任免除' in text and ('第六条' in text or '第七条' in text or '第八条' in text):
            return True
        if '赔偿处理' in text and ('第二十六条' in text or '第二十八条' in text):
            return True
        return False

    @staticmethod
    def _is_real_list_page(text: str) -> bool:
        """判断是否真的"人员清单"页（含表头词 + 证件号模式）"""
        has_header = any(kw in text for kw in ["姓名", "证件号", "证件号码", "雇员姓名"])
        has_id_evidence = bool(re.search(r'\d{6,}', text))
        return has_header and has_id_evidence

    @staticmethod
    def _is_list_continuation_page(text: str) -> bool:
        """判断是否为清单续页（无表头词但含多条 18 位身份证片段）。

        真实场景：大型保单清单分多页时，从第 2 页开始常**不再重复表头词**（节省版面）。
        此时用"含 ≥3 个 18 位身份证片段"作为强证据判断它仍是清单续页。

        返回 True 表示这页仍是清单的一部分（应继续扩展）。
        """
        if not text:
            return False
        # 先做跨行拼接（PyMuPDF 可能把 18 位 ID 拆成两行）
        joined = re.sub(r'(\d{3,})\n(\d|[Xx])', r'\1\2', text)
        ids = re.findall(r'\d{17}[\dXx]', joined)
        # 至少 3 个 18 位身份证 = 强烈的清单续页信号
        return len(ids) >= 3

    @staticmethod
    def _find_list_pages(pdf_doc: PDFDocument) -> list[int]:
        """定位人员清单所在页（精确版）

        流程：
        1) 标记命中：扫描所有页找含"人员名单"/"雇员清单"等 _LIST_MARKERS 的页
        2) 真实清单筛选：剔除条款误触发（仅当 _is_real_list_page 为 True 才保留）
        3) 跨页扩展：从真实清单页向后扩展。续页判定（任一满足即算）：
           a) _is_real_list_page 命中（续页又印了表头）
           b) _is_list_continuation_page 命中（续页无表头但 ≥3 个 18 位 ID）— 2026-09-14 新增
           c) 含 6+ 位连续数字 + 表头词（兜底）
           跳过条款页/页脚页；遇到完全无关页面则停止扩展。
        """
        # 1) 标记命中
        candidate_page_nums = []
        for page in pdf_doc.pages:
            if not page.has_meaningful_text:
                continue
            for marker in _LIST_MARKERS:
                if marker in page.text:
                    candidate_page_nums.append(page.page_number)
                    break
            else:
                for marker in _INLINE_MARKERS:
                    if marker in page.text:
                        candidate_page_nums.append(page.page_number)
                        break

        # 2) 真实清单筛选
        list_page_nums = []
        for lpn in candidate_page_nums:
            page = next((p for p in pdf_doc.pages if p.page_number == lpn), None)
            if not page:
                continue
            if not MetadataExtractorNode._is_real_list_page(page.text):
                continue
            list_page_nums.append(lpn)

        # 3) 跨页扩展
        result = []
        for lpn in list_page_nums:
            if lpn not in result:
                result.append(lpn)
            # 从 lpn+1 开始向后扫描
            for page in pdf_doc.pages:
                if page.page_number <= lpn:
                    continue
                if page.page_number in result:
                    continue
                if not page.has_meaningful_text:
                    continue
                # 跳过条款/职业分类表/页脚
                if MetadataExtractorNode._is_clause_page(page.text):
                    continue
                if re.match(r'^\s*第\s*\d+\s*页\s*/\s*共\s*\d+\s*页\s*$', page.text):
                    continue
                # 命中真实清单续页标记（含表头）
                if MetadataExtractorNode._is_real_list_page(page.text):
                    result.append(page.page_number)
                    continue
                # 2026-09-14 新增：续页判定（无表头词但 ≥3 个 18 位身份证）
                # 大型保单（百人以上）常省略重复表头，需用 ID 数兜底
                if MetadataExtractorNode._is_list_continuation_page(page.text):
                    result.append(page.page_number)
                    continue
                # 含 6+ 连续数字且有表头词 → 兜底算清单续页
                has_id_evidence = re.search(r'\d{6,}', page.text) and any(
                    kw in page.text for kw in ["姓名", "证件号", "证件号码", "雇员姓名"]
                )
                if has_id_evidence:
                    result.append(page.page_number)
                    continue
                # 否则停止扩展（无关页）
                break
        return sorted(result)

    @staticmethod
    def _is_unlisted_policy(text: str) -> bool:
        """检测是否为不记名投保保单（只有总人数，没有逐人清单）

        特征：包含"是否记名投保"且后跟"否"，或"灵工版 + 总投保员工人数"。

        注意：不能仅凭"不记名投保"字样判断，因为雇主责任险条款中常出现
        "保险单约定不记名投保的……"这类通用条款文字，会误伤记名保单。
        """
        # 灵工版 + 总投保员工人数（灵工版默认不记名）
        if "灵工" in text and "总投保员工人数" in text:
            return True
        # "是否记名投保"字段明确回答"否" → 不记名
        if re.search(r"是否记名投保[：:\s]*否", text):
            return True
        return False

    @staticmethod
    def _is_individual_policy(text: str) -> bool:
        """检测是否为个人保单（被保险人信息以键值对形式内嵌）

        特征：包含"被保险人信息" + "中文姓名" + "证件号码" 且
        不包含人员清单/表格标记（否则走 table/inline 路径）。
        """
        has_insured_section = any(m in text for m in _INDIVIDUAL_MARKERS)
        has_name_label = "中文姓名" in text or "被保险人姓名" in text
        has_id_label = "证件号码" in text or "身份证号" in text
        return has_insured_section and has_name_label and has_id_label

    @staticmethod
    def _find_individual_pages(pdf_doc: PDFDocument) -> list[int]:
        """定位包含"被保险人信息"的页面"""
        result = []
        for page in pdf_doc.pages:
            if not page.has_meaningful_text:
                continue
            for marker in _INDIVIDUAL_MARKERS:
                if marker in page.text:
                    result.append(page.page_number)
                    break
        return sorted(result)


def metadata_extractor_node(state: InvoiceRecognitionState) -> dict:
    raise NotImplementedError("应在 graph builder 中通过 functools.partial 注入")
