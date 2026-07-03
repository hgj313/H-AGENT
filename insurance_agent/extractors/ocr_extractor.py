"""OCR Extractor - 扫描件走视觉模型 OCR（Phase 3 实现）

使用项目底座 LLM（kimi-k2.6 视觉模型）处理扫描件 PDF。
失败透传：LLM 调用失败直接抛异常，不兜底。
"""

import base64
import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage

from insurance_agent.domain import InsuredPerson
from .base import BaseExtractor
from insurance_agent.tools import parse_json_strict


logger = logging.getLogger(__name__)

# OCR Prompt：强制返回 JSON，不输出解释
_OCR_PROMPT = """你是一个保险单识别专家。请识别图片中的被保人员清单，提取以下字段：
- name: 姓名
- id_number: 证件号码（身份证号）
- company: 所属公司（如无法识别可留空）
- start_date: 起始时间（如无法识别可留空，格式 YYYY-MM-DD）
- end_date: 终止时间（如无法识别可留空，格式 YYYY-MM-DD）

请以 JSON 数组格式返回，例如：
[{"name": "张三", "id_number": "110101199003078811", "company": "测试公司", "start_date": "2024-01-01", "end_date": "2024-12-31"}]

只返回 JSON 数组，不要有任何其他文字说明。
如果图片中没有人员清单，返回 []。
"""


class OCRExtractor(BaseExtractor):
    """OCR 提取器（扫描件）

    依赖：LLM 视觉模型（项目底座：kimi-k2.6）。

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

        for page_num, img_b64 in enumerate(page_images, start=1):
            persons = self._ocr_page(img_b64, page_num)
            # 补充 policy_holder（如 OCR 未识别公司名）
            for p in persons:
                if not p.company and policy_holder:
                    p.company = policy_holder
            all_persons.extend(persons)

        return all_persons

    def _ocr_page(self, img_b64: str, page_num: int) -> list[InsuredPerson]:
        """对单页图片调用视觉模型 OCR"""
        # 构造多模态消息（图片 + 文字 prompt）
        # kimi-k2.6 通过 DashScope OpenAI 协议支持 image_url (base64)
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
        response = self._llm.invoke([message])
        raw = response.content if hasattr(response, "content") else str(response)

        logger.info(f"OCR 原始返回（第 {page_num} 页）: {raw[:200]}")

        # 解析 JSON（三重保险：json_stabilizer）
        parsed = parse_json_strict(raw)
        if not isinstance(parsed, list):
            logger.warning(f"OCR 返回非列表格式: {type(parsed)}，跳过")
            return []

        # 映射为 InsuredPerson
        persons: list[InsuredPerson] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            p = InsuredPerson(
                name=item.get("name", "").strip(),
                id_number=item.get("id_number", "").strip(),
                id_type="身份证" if item.get("id_number") else "",
                company=item.get("company", "").strip(),
                start_date=item.get("start_date", "") or None,
                end_date=item.get("end_date", "") or None,
                confidence=0.8,  # OCR 置信度默认 0.8
            )
            if p.name:  # 只保留有名字的
                persons.append(p)

        logger.info(f"OCR 第 {page_num} 页提取 {len(persons)} 人")
        return persons
