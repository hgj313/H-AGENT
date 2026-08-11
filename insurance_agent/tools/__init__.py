"""通用工具层

按通用性 / 可复用性 放置。**不依赖** insurance 业务。
任何 Agent 都可以复用这里的工具。
"""

from .id_validator import (
    is_valid_chinese_id,
    extract_chinese_id_from_text,
    normalize_id,
)
from .id_reconstructor import (
    is_masked_id,
    reconstruct_masked_id,
    reconstruct_persons_ids,
    calculate_checksum,
    parse_birth_date,
)
from .date_parser import (
    extract_overall_insurance_period,
    extract_dates_near,
    normalize_date,
)
from .company_extractor import (
    extract_company_name,
    extract_company_after_label,
)
from .name_extractor import (
    extract_chinese_name,
    extract_names_near,
)
from .text_cleaner import clean_pdf_text
from .json_stabilizer import parse_json_strict, build_tool_schema_response_format
from .filename_parser import (
    parse_policy_filename,
    is_main_policy,
    is_endorsement,
    extract_company_from_filename,
    FilenameInfo,
)
from .excel_sync import (
    sync_excel_with_extraction,
    sync_excel_from_json,
)
from .erp_uploader import (
    upload_excel_to_erp,
    upload_excel_to_erp_with_session_manager,
)

__all__ = [
    # ID
    "is_valid_chinese_id",
    "extract_chinese_id_from_text",
    "normalize_id",
    # ID Reconstruction
    "is_masked_id",
    "reconstruct_masked_id",
    "reconstruct_persons_ids",
    "calculate_checksum",
    "parse_birth_date",
    # Date
    "extract_overall_insurance_period",
    "extract_dates_near",
    "normalize_date",
    # Company
    "extract_company_name",
    "extract_company_after_label",
    # Name
    "extract_chinese_name",
    "extract_names_near",
    # Text
    "clean_pdf_text",
    # JSON
    "parse_json_strict",
    "build_tool_schema_response_format",
    # Filename
    "parse_policy_filename",
    "is_main_policy",
    "is_endorsement",
    "extract_company_from_filename",
    "FilenameInfo",
    # Excel Sync
    "sync_excel_with_extraction",
    "sync_excel_from_json",
    # ERP Upload
    "upload_excel_to_erp",
    "upload_excel_to_erp_with_session_manager",
]
