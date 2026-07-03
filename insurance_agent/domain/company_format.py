"""CompanyFormat & FieldMapping - 领域模型：保险公司格式模式

每个保险公司有自己的人员清单格式（表头/行内/有无逐人日期等）。
格式被学习后存入 FormatRegistry，下次遇到同公司保单可快速定位。
"""

from dataclasses import dataclass, field


@dataclass
class FieldMapping:
    """标准字段 → 保险公司字段的映射"""
    standard_field: str   # 标准字段名 (name/id_number/start_date/...)
    company_field: str    # 保险公司实际用的字段名
    field_type: str = "text"  # text / date / number
    date_format: str = ""     # 仅 date 类型有效


@dataclass
class CompanyFormat:
    """某家保险公司的格式模式"""
    company_name: str
    list_title_pattern: str = ""        # 人员清单页标题模式 (如 "人员清单")
    list_page_marker: str = ""          # 定位清单页的标记
    field_mappings: list[FieldMapping] = field(default_factory=list)
    table_type: str = "table"           # table / inline / mixed
    has_per_person_dates: bool = False  # 是否有逐人起止时间
    overall_date_pattern: str = ""      # 整体保险期正则
    date_fields_in_table: list[str] = field(default_factory=list)
    notes: str = ""
    confidence: float = 0.0
