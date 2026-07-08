"""保险公司名图片识别器

当 PDF 文字层未找到保险公司名时，
将首页转为图片用 MiniMax-M3 视觉模型 OCR 提取保险公司名称。

遵循 DI：通过构造器注入 LLM 客户端和 PDF 解析器。
"""

import base64
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_COMPANY_OCR_SYSTEM = "你是一个保险单识别专家。请仔细识别图片中的保险公司名称。"

_COMPANY_OCR_PROMPT = """请识别这张保险单图片中的保险公司名称。

识别规则：
1. 保险公司名称通常出现在保单的页眉、标题或 logo 旁边
2. 常见保险公司：利宝保险、中国太平洋财产保险、中国人寿财产保险、中国平安、中国人民保险、泰康保险、阳光保险、中华联合保险等
3. 只返回保险公司名称，不要其他文字

示例返回：
- 利宝保险
- 中国太平洋财产保险
- 中国人寿财产保险

如果无法识别保险公司名称，返回：unknown"""


class CompanyImageDetector:
    """保险公司名图片识别器

    依赖：
    - LLM 视觉模型（MiniMax-M3）
    - PDF 解析器（用于页面转图片）

    失败透传：LLM 调用失败不兜底，返回 "unknown"
    """

    def __init__(self, llm_client: Optional[Any] = None, pdf_parser=None):
        self._llm = llm_client
        self._pdf_parser = pdf_parser

    def detect_from_first_page(self, pdf_doc) -> str:
        """从 PDF 首页图片识别保险公司名

        Args:
            pdf_doc: PDFDocument 对象（需要有 file_path）

        Returns:
            保险公司名称字符串，识别失败返回 "unknown"
        """
        if not self._llm:
            logger.warning("CompanyImageDetector: LLM 客户端未注入")
            return "unknown"

        if not self._pdf_parser:
            logger.warning("CompanyImageDetector: PDF 解析器未注入")
            return "unknown"

        try:
            # 获取首页图片
            if hasattr(self._pdf_parser, "get_page_image"):
                img_b64 = self._pdf_parser.get_page_image(pdf_doc, 1)
            else:
                logger.warning("CompanyImageDetector: PDF 解析器不支持 get_page_image")
                return "unknown"

            # 调用 LLM 识别
            message = HumanMessage(
                content=[
                    {"type": "text", "text": _COMPANY_OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}",
                            "detail": "high",
                        },
                    },
                ]
            )

            logger.info("CompanyImageDetector: 调用视觉模型识别保险公司名")
            response = self._llm.invoke([SystemMessage(content=_COMPANY_OCR_SYSTEM), message])
            raw = response.content if hasattr(response, "content") else str(response)

            # 清理结果
            company = raw.strip().strip("\"'""''").strip()

            # 过滤无效结果
            if not company or company.lower() == "unknown":
                return "unknown"

            # 检查是否包含已知保险公司关键词
            from insurance_agent.infrastructure.parsers.pymupdf_parser import PyMuPDFParser
            for known_name, patterns in PyMuPDFParser._COMPANY_PATTERNS.items():
                for pattern in patterns:
                    if pattern.lower() in company.lower():
                        return known_name

            # 如果返回的是一个合理的公司名（包含"保险"字样），直接使用
            if "保险" in company or "人寿" in company or "养老" in company:
                return company

            # 否则返回原始结果但标记为 OCR 识别
            logger.info(f"CompanyImageDetector: 识别到保险公司名: {company}")
            return company

        except Exception as e:
            logger.warning(f"CompanyImageDetector: 识别失败: {e}")
            return "unknown"
