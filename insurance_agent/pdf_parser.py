"""
PDF Parser Module

Handles both text-based and scanned PDFs:
- Text PDFs: Extract text directly via pymupdf
- Scanned PDFs: Convert to images for vision model OCR

DDD Layers:
- Protocol: PDFParserProtocol (interface)
- Domain: PDFPage, PDFDocument (domain models)
- Adapter: PyMuPDFParser (pymupdf implementation)
"""

import pymupdf
import os
import base64
from dataclasses import dataclass, field
from typing import Protocol, Optional


# === Domain Models ===

@dataclass
class PDFPage:
    """Single page of a PDF document"""
    page_number: int
    text: str = ""
    image_base64: Optional[str] = None  # Base64 encoded page image (for OCR)
    has_meaningful_text: bool = False
    text_length: int = 0


@dataclass
class PDFDocument:
    """Complete PDF document"""
    file_path: str
    file_name: str
    total_pages: int
    pages: list[PDFPage] = field(default_factory=list)
    is_scanned: bool = False  # True if most pages lack text layer
    insurance_company: str = ""  # Detected insurance company name


# === Protocol (Interface) ===

class PDFParserProtocol(Protocol):
    """PDF parser interface following DI principle"""

    def parse(self, file_path: str) -> PDFDocument:
        """Parse a PDF file into a PDFDocument"""
        ...

    def get_page_image(self, doc: PDFDocument, page_number: int) -> str:
        """Get base64 encoded image of a specific page"""
        ...


# === Adapter (Implementation) ===

class PyMuPDFParser:
    """PDF parser using pymupdf library

    Strategy:
    1. Try extracting text layer first (fast, free)
    2. If text layer is empty/minimal, mark as scanned -> convert to image
    3. Support selective page image generation (only for pages needing OCR)
    """

    # Minimum text length to consider a page as having meaningful text
    MIN_TEXT_LENGTH = 30

    # DPI for image conversion (higher = better OCR accuracy)
    IMAGE_DPI = 200

    def parse(self, file_path: str) -> PDFDocument:
        """Parse PDF into structured document"""
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
            # Clean up special characters
            clean_text = raw_text.replace('\uffff', '').replace('\xa0', ' ')
            text_length = len(clean_text.strip())
            has_text = text_length >= self.MIN_TEXT_LENGTH

            if has_text:
                pages_with_text += 1

            pdf_page = PDFPage(
                page_number=page_num + 1,
                text=clean_text,
                has_meaningful_text=has_text,
                text_length=text_length,
            )
            pdf_doc.pages.append(pdf_page)

        # Determine if scanned
        pdf_doc.is_scanned = pages_with_text < total_pages * 0.5

        # Try to detect insurance company from text
        pdf_doc.insurance_company = self._detect_insurance_company(pdf_doc)

        doc.close()
        return pdf_doc

    def get_page_image(self, pdf_doc: PDFDocument, page_number: int) -> str:
        """Convert a specific page to base64 image for OCR"""
        doc = pymupdf.open(pdf_doc.file_path)
        page_idx = page_number - 1  # Convert to 0-based index

        if page_idx >= len(doc) or page_idx < 0:
            doc.close()
            raise ValueError(f"Page {page_number} out of range (1-{len(doc)})")

        page = doc[page_idx]
        # Convert page to image
        pix = page.get_pixmap(dpi=self.IMAGE_DPI)
        img_bytes = pix.tobytes("png")
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")

        doc.close()
        return img_base64

    def get_all_page_images(self, pdf_doc: PDFDocument) -> list[str]:
        """Convert all pages to base64 images (for fully scanned PDFs)"""
        images = []
        for page in pdf_doc.pages:
            if not page.has_meaningful_text:
                img = self.get_page_image(pdf_doc, page.page_number)
                images.append(img)
                page.image_base64 = img
        return images

    def _detect_insurance_company(self, pdf_doc: PDFDocument) -> str:
        """Detect insurance company from extracted text"""
        all_text = " ".join(p.text for p in pdf_doc.pages if p.has_meaningful_text)

        # Known insurance company patterns
        companies = {
            "利宝保险": ["利宝保险", "Liberty", "libertymutual"],
            "中国太平洋财产保险": ["太平洋财产保险", "太平洋", "cpic", "95500"],
            "中国人寿": ["中国人寿", "China Life"],
            "中国平安": ["平安", "Ping An"],
            "中国人民保险": ["人民保险", "PICC"],
            "泰康保险": ["泰康"],
            "阳光保险": ["阳光"],
            "中华联合保险": ["中华联合"],
        }

        for company_name, patterns in companies.items():
            for pattern in patterns:
                if pattern.lower() in all_text.lower():
                    return company_name

        return "unknown"
