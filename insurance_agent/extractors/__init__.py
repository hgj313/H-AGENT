"""Extractors

提取策略：按保险公司保单格式分类。
每个 Extractor 接收页面文本，输出 InsuredPerson 列表。
"""

from .base import BaseExtractor
from .table_extractor import TableExtractor
from .inline_extractor import InlineExtractor
from .ocr_extractor import OCRExtractor

__all__ = [
    "BaseExtractor",
    "TableExtractor",
    "InlineExtractor",
    "OCRExtractor",
]
