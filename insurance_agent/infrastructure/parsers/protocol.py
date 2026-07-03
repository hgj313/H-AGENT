"""PDF Parser Protocol (DI Interface)"""

from typing import Protocol
from insurance_agent.domain import PDFDocument


class PDFParserProtocol(Protocol):
    """PDF 解析接口（实现可替换：pymupdf / pdfplumber / 其它）"""

    def parse(self, file_path: str) -> PDFDocument:
        """解析 PDF 文件为结构化文档"""
        ...

    def get_page_image(self, doc: PDFDocument, page_number: int) -> str:
        """获取指定页的 base64 编码图片（用于 OCR）"""
        ...
