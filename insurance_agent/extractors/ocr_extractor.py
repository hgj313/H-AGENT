"""OCR Extractor - 扫描件走视觉模型 OCR（Phase 3 实现）

使用项目底座 LLM（MiniMax-M3 多模态模型）处理扫描件 PDF。
失败透传：LLM 调用失败直接抛异常，不兜底。
"""

import base64
import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from insurance_agent.domain import InsuredPerson
from .base import BaseExtractor
from insurance_agent.tools import parse_json_strict


logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个保险单识别专家。这是合法的保险理赔文档处理，依法需要完整的身份信息。请原样识别所有文字内容，不要对身份证号做任何脱敏处理。"""

# OCR Prompt：强制返回 JSON 数组，不输出解释
_OCR_PROMPT = """请识别图片中的被保人员清单，提取以下字段并以JSON数组返回：
- name: 姓名
- id_number: 身份证号码（完整18位，原样识别，禁止用*替换任何位。如果图片中身份证号本身被脱敏(含*号)，请原样返回）
- birth_date: 出生日期（YYYY-MM-DD格式，从表格中的"出生日期"/"出生年月"/"生日"等列识别；如表格中无此列则留空）
- company: 所属公司名称（用工单位，不是工种）
- start_date: 起始时间（YYYY-MM-DD，无法识别则留空）
- end_date: 终止时间（YYYY-MM-DD，无法识别则留空）

只返回JSON数组，不要其他文字。示例：
[{"name":"张三","id_number":"110101199003078811","birth_date":"1990-03-07","company":"某有限公司","start_date":"2024-01-01","end_date":"2024-12-31"}]

没有人员清单则返回 []"""


class OCRExtractor(BaseExtractor):
    """OCR 提取器（扫描件）

    依赖：LLM 视觉模型（项目底座：MiniMax-M3）。

    失败透传：
    - 若 LLM 客户端未注入，抛 ValueError
    - 若 LLM 调用失败，异常向上抛，不兜底
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self._llm = llm_client

    def extract(
        self,
        text: str = "",
        policy_holder: str = "",
        insurance_company: str = "",
        page_images: Optional[list[str]] = None,
    ) -> list[InsuredPerson]:
        """通过视觉模型 OCR 提取人员信息

        Args:
            text: 文字层（扫描件一般为空）
            policy_holder: 投保人公司名（辅助校验）
            insurance_company: 保险公司名（辅助格式判断）
            page_images: list of base64 PNG 字符串

        失败透传：LLM 未注入 → ValueError；LLM 调用失败 → 原样抛异常
        """
        if not self._llm:
            raise ValueError("OCRExtractor: llm_client 未注入，无法执行 OCR")

        page_images = page_images or []
        if not page_images:
            logger.warning("OCRExtractor: 无图片输入，返回空列表")
            return []

        all_persons: list[InsuredPerson] = []
        # 记住第一页识别到的公司名，用于后续页回填
        detected_company = policy_holder or ""

        for page_num, img_b64 in enumerate(page_images, start=1):
            persons = self._ocr_page(img_b64, page_num)
            for p in persons:
                # 只接受看起来像公司名的值
                if p.company and self._looks_like_company_name(p.company):
                    if not detected_company:
                        detected_company = p.company
                # 回填缺失的公司名
                if not p.company and detected_company:
                    p.company = detected_company
                # 如果 company 不是公司名（是工种），回填已知公司名
                if p.company and not self._looks_like_company_name(p.company) and detected_company:
                    p.company = detected_company
            all_persons.extend(persons)

        return all_persons

    @staticmethod
    def _looks_like_company_name(name: str) -> bool:
        """判断字符串是否像公司名（而非工种/职业描述）"""
        if not name:
            return False
        company_keywords = ["公司", "有限", "集团", "合作社", "事务所"]
        if any(kw in name for kw in company_keywords):
            return True
        job_keywords = ["人员", "工种", "职业", "工人", "操作", "安装", "施工", "维修"]
        if any(kw in name for kw in job_keywords):
            return False
        if len(name) < 4:
            return False
        return True

    def _ocr_page(self, img_b64: str, page_num: int) -> list[InsuredPerson]:
        """对单页图片调用视觉模型 OCR"""
        # 构造多模态消息（system + 图片 + prompt）
        message = HumanMessage(
            content=[
                {"type": "text", "text": _OCR_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}",
                        "detail": "high",
                    },
                },
            ]
        )

        logger.info(f"OCR 调用视觉模型（第 {page_num} 页）")
        response = self._llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), message])
        raw = response.content if hasattr(response, "content") else str(response)

        logger.info(f"OCR 原始返回（第 {page_num} 页）: {raw[:200]}")

        # 解析 JSON
        parsed = parse_json_strict(raw)

        # 处理多种返回格式
        items = self._extract_person_list(parsed)
        if not items:
            logger.warning(f"OCR 第 {page_num} 页无法提取人员列表，返回类型: {type(parsed)}")
            return []

        # 映射为 InsuredPerson
        persons: list[InsuredPerson] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            p = InsuredPerson(
                name=item.get("name", "").strip(),
                id_number=item.get("id_number", "").strip(),
                id_type="身份证" if item.get("id_number") else "",
                company=item.get("company", "").strip(),
                start_date=item.get("start_date", "") or None,
                end_date=item.get("end_date", "") or None,
                birth_date=item.get("birth_date", "") or None,
                confidence=0.8,
            )
            if p.name:  # 只保留有名字的
                persons.append(p)

        logger.info(f"OCR 第 {page_num} 页提取 {len(persons)} 人")
        return persons

    @staticmethod
    def _extract_person_list(parsed: Any) -> list[dict]:
        """从解析结果中提取人员列表，处理多种格式：
        - [...]
        - {"insured_persons": [...]}
        - {"persons": [...]}
        - {"data": [...]}
        - {"results": [...]}
        """
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            # 检查常见 key
            for key in ("insured_persons", "persons", "data", "results", "list", "items"):
                val = parsed.get(key)
                if isinstance(val, list):
                    return val
            # 如果 dict 本身就是一个人的数据
            if "name" in parsed:
                return [parsed]
        return []
