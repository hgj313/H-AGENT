"""Format Registry (基础设施层)

负责保险公司格式模式的持久化与检索。
"""

import os
import json
from typing import Protocol, Optional
from dataclasses import asdict

from insurance_agent.domain import CompanyFormat, FieldMapping


class FormatRegistryProtocol(Protocol):
    """格式注册表接口（DI）"""

    def get_format(self, company_name: str) -> Optional[CompanyFormat]: ...
    def save_format(self, fmt: CompanyFormat) -> None: ...
    def list_companies(self) -> list[str]: ...


class JSONFormatRegistry:
    """基于 JSON 文件的格式注册表实现

    数据文件路径：insurance_agent/data/format_registry.json
    """

    DEFAULT_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "format_registry.json"
    )

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path or self.DEFAULT_PATH
        self._formats: dict[str, CompanyFormat] = {}
        self._load()

    def _load(self):
        """从 JSON 加载已学习的格式模式"""
        if not os.path.exists(self.storage_path):
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            self._save()
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for company_name, fmt_data in data.items():
                mappings = [FieldMapping(**m) for m in fmt_data.get("field_mappings", [])]
                fmt_data["field_mappings"] = mappings
                self._formats[company_name] = CompanyFormat(**fmt_data)
        except (json.JSONDecodeError, FileNotFoundError, TypeError):
            self._formats = {}

    def _save(self):
        """将格式模式持久化到 JSON"""
        data = {}
        for company_name, fmt in self._formats.items():
            data[company_name] = asdict(fmt)

        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_format(self, company_name: str) -> Optional[CompanyFormat]:
        """获取某家保险公司的格式模式"""
        return self._formats.get(company_name)

    def save_format(self, fmt: CompanyFormat) -> None:
        """保存（覆盖）某家保险公司的格式模式"""
        self._formats[fmt.company_name] = fmt
        self._save()

    def list_companies(self) -> list[str]:
        """列出所有已学习的保险公司"""
        return list(self._formats.keys())
