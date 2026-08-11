"""PyMuPDF Parser - pymupdf 实现的 PDF 解析器

策略：
1. 优先提取文字层（快速、免费）
2. 文字层缺失时，标记为扫描件，可转图片供视觉模型使用
"""

import os
import base64
import pymupdf

from insurance_agent.domain import PDFDocument, PDFPage
from insurance_agent.tools import clean_pdf_text
from .protocol import PDFParserProtocol


class PyMuPDFParser:
    """基于 pymupdf 的 PDF 解析器

    配置项：
    - min_text_length: 单页文字少于该值视为无文字层
    - image_dpi: 扫描件转图片的 DPI（越高 OCR 越准，但越慢）
    """

    MIN_TEXT_LENGTH = 30
    IMAGE_DPI = 200

    # 已知保险公司名称（用于从文字层识别）
    _COMPANY_PATTERNS = {
        "利宝保险": ["利宝保险", "Liberty", "libertymutual"],
        "中国太平洋财产保险": ["太平洋财产保险", "中国太平洋", "cpic", "95500"],
        "中国人寿财产保险": ["中国人寿财产保险", "中国人寿财险"],
        "中国人寿": ["中国人寿"],
        "中国平安": ["平安保险", "平安养老", "Ping An"],
        "中国人民保险": ["人民保险", "PICC"],
        "泰康保险": ["泰康"],
        "阳光保险": ["阳光"],
        "中华联合保险": ["中华联合"],
        "太平养老": ["太平养老"],
        "大家养老": ["大家养老"],
        "新华人寿": ["新华人寿", "新华保险"],
        "友邦保险": ["友邦保险", "AIA"],
        # Phase 4 新增
        "众安在线财产保险": ["众安在线", "众安保险", "zhongan", "952299"],
        "华农财产保险": ["华农财产保险"],
        "黄河财产保险": ["黄河财产保险", "ypic"],
        "珠峰财产保险": ["珠峰财产保险"],
        "国泰财产保险": ["国泰财产保险"],
        "亚太财产保险": ["亚太财产保险"],
        "紫金财产保险": ["紫金财产保险"],
        "永安财产保险": ["永安财产保险"],
    }

    def parse(self, file_path: str) -> PDFDocument:
        """解析 PDF 为 PDFDocument"""
        doc = pymupdf.open(file_path)
        total_pages = len(doc)

        pdf_doc = PDFDocument(
            file_path=file_path,
            file_name=os.path.basename(file_path),
            total_pages=total_pages,
        )

        pages_with_text = 0
        for page_num in range(total_pages):
            page = doc[page_num]
            raw_text = page.get_text("text")
            clean_text = clean_pdf_text(raw_text)
            text_length = len(clean_text)
            has_text = text_length >= self.MIN_TEXT_LENGTH

            if has_text:
                pages_with_text += 1

            pdf_doc.pages.append(PDFPage(
                page_number=page_num + 1,
                text=clean_text,
                has_meaningful_text=has_text,
                text_length=text_length,
            ))

        pdf_doc.is_scanned = pages_with_text < total_pages * 0.5
        pdf_doc.insurance_company = self._detect_insurance_company(pdf_doc)

        doc.close()
        return pdf_doc

    def get_page_image(self, pdf_doc: PDFDocument, page_number: int) -> str:
        """获取指定页的 base64 PNG 图片（供视觉模型 OCR 使用）"""
        doc = pymupdf.open(pdf_doc.file_path)
        page_idx = page_number - 1

        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            raise ValueError(f"Page {page_number} out of range (1-{len(doc)})")

        page = doc[page_idx]
        pix = page.get_pixmap(dpi=self.IMAGE_DPI)
        img_bytes = pix.tobytes("png")
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")

        doc.close()
        return img_base64

    def get_page_images(self, pdf_doc: PDFDocument) -> list[str]:
        """获取所有页的 base64 PNG 图片列表（供视觉模型 OCR 使用）

        扫描件转换所有页；文字层 PDF 也转换所有页（list_pages 由下游节点补充）。
        """
        doc = pymupdf.open(pdf_doc.file_path)
        images: list[str] = []

        for page_num in range(1, len(doc) + 1):
            page = doc[page_num - 1]
            pix = page.get_pixmap(dpi=self.IMAGE_DPI)
            img_bytes = pix.tobytes("png")
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")
            images.append(img_base64)

        doc.close()
        return images

    def _detect_insurance_company(self, pdf_doc: PDFDocument) -> str:
        """从所有页面文字中识别保险公司名"""
        all_text = " ".join(p.text for p in pdf_doc.pages if p.has_meaningful_text)
        if not all_text:
            return "unknown"

        all_text_lower = all_text.lower()
        for company_name, patterns in self._COMPANY_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in all_text_lower:
                    return company_name

        return "unknown"
