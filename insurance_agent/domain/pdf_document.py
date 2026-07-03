"""PDFDocument & PDFPage - 领域模型：PDF 解析结果

这是 PDF 解析后产出的纯数据结构，不依赖具体解析库。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PDFPage:
    """PDF 单页"""
    page_number: int
    text: str = ""
    image_base64: Optional[str] = None
    has_meaningful_text: bool = False
    text_length: int = 0


@dataclass
class PDFDocument:
    """PDF 整本文档"""
    file_path: str
    file_name: str
    total_pages: int
    pages: list[PDFPage] = field(default_factory=list)
    is_scanned: bool = False
    insurance_company: str = ""
