"""
Format Registry Module

Stores and retrieves insurance company format patterns.
Each insurance company has a unique personnel list format that can be learned
and reused for faster extraction in future encounters.

DDD Layers:
- Protocol: FormatRegistryProtocol
- Domain: CompanyFormat, FieldMapping
- Adapter: JSONFormatRegistry (file-based storage)
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Protocol, Optional


# === Domain Models ===

@dataclass
class FieldMapping:
    """Maps a standard field to the insurance company's specific field name"""
    standard_field: str  # Standard field name (e.g., "name", "id_number")
    company_field: str   # Company-specific field name (e.g., "雇员姓名", "姓名")
    field_type: str = "text"  # text, date, number
    date_format: str = ""     # Date format if field_type is date


@dataclass
class CompanyFormat:
    """Format pattern for a specific insurance company"""
    company_name: str
    list_title_pattern: str      # Pattern to identify the personnel list page
    list_page_marker: str        # Text marker indicating personnel list start
    field_mappings: list[FieldMapping] = field(default_factory=list)
    table_type: str = "table"    # table, inline, mixed
    has_per_person_dates: bool = False  # Whether each person has individual start/end dates
    overall_date_pattern: str = ""      # Pattern for overall insurance period
    date_fields_in_table: list[str] = field(default_factory=list)  # Which columns contain dates
    notes: str = ""
    confidence: float = 0.0     # Learning confidence (0-1)


# === Protocol ===

class FormatRegistryProtocol(Protocol):
    """Format registry interface"""
    def get_format(self, company_name: str) -> Optional[CompanyFormat]:
        ...

    def save_format(self, format: CompanyFormat) -> None:
        ...

    def list_companies(self) -> list[str]:
        ...


# === Adapter ===

class JSONFormatRegistry:
    """File-based format registry using JSON storage

    Format patterns are stored in a JSON file and loaded on demand.
    New patterns discovered during extraction are saved back.
    """

    STORAGE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "insurance_agent", "data", "format_registry.json"
    )

    def __init__(self, storage_path: str = None):
        self.storage_path = storage_path or self.STORAGE_PATH
        self._formats: dict[str, CompanyFormat] = {}
        self._load()

    def _load(self):
        """Load formats from JSON file"""
        if not os.path.exists(self.storage_path):
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            self._save()  # Create empty file
            return

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for company_name, format_data in data.items():
                mappings = [
                    FieldMapping(**m) for m in format_data.get("field_mappings", [])
                ]
                format_data["field_mappings"] = mappings
                self._formats[company_name] = CompanyFormat(**format_data)
        except (json.JSONDecodeError, FileNotFoundError):
            self._formats = {}

    def _save(self):
        """Save formats to JSON file"""
        data = {}
        for company_name, format in self._formats.items():
            format_dict = asdict(format)
            data[company_name] = format_dict

        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_format(self, company_name: str) -> Optional[CompanyFormat]:
        """Get format pattern for a known insurance company"""
        return self._formats.get(company_name)

    def save_format(self, format: CompanyFormat) -> None:
        """Save a newly discovered format pattern"""
        self._formats[format.company_name] = format
        self._save()

    def list_companies(self) -> list[str]:
        """List all known insurance company names"""
        return list(self._formats.keys())

    def update_format(self, company_name: str, **updates) -> None:
        """Update an existing format pattern"""
        if company_name not in self._formats:
            return

        format = self._formats[company_name]
        for key, value in updates.items():
            if hasattr(format, key):
                setattr(format, key, value)

        self._save()
