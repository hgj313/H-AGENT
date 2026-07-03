"""Infrastructure Layer

基础设施层：与外部系统对接（PDF 解析库、LLM API、本地存储）。
所有实现都通过 Protocol 暴露接口，遵循 DI 原则。
"""

from .parsers import PyMuPDFParser, PDFParserProtocol
from .format_registry import JSONFormatRegistry, FormatRegistryProtocol
from .llm import LLMFactory, LLMConfig, LLMProvider, get_llm_factory

__all__ = [
    "PyMuPDFParser",
    "PDFParserProtocol",
    "JSONFormatRegistry",
    "FormatRegistryProtocol",
    "LLMFactory",
    "LLMConfig",
    "LLMProvider",
    "get_llm_factory",
]
