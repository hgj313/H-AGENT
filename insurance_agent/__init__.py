"""
Insurance Policy Recognition Agent

A modular agent for extracting insured personnel lists from insurance policy PDFs.
Supports multiple insurance companies with different formats.
"""

from insurance_agent.extractor import PolicyExtractor
from insurance_agent.format_registry import JSONFormatRegistry
from insurance_agent.pdf_parser import PyMuPDFParser

__all__ = ["PolicyExtractor", "JSONFormatRegistry", "PyMuPDFParser"]
