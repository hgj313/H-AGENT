"""Domain Models

领域模型：纯数据类，不依赖任何 infrastructure。
任何 infrastructure 层 / agent 层 / tool 层都依赖 domain，
domain 永远不反向依赖。
"""

from .insured_person import InsuredPerson
from .extraction_result import ExtractionResult
from .company_format import FieldMapping, CompanyFormat
from .pdf_document import PDFPage, PDFDocument

__all__ = [
    "InsuredPerson",
    "ExtractionResult",
    "FieldMapping",
    "CompanyFormat",
    "PDFPage",
    "PDFDocument",
]
