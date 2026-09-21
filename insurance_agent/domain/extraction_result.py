"""ExtractionResult - 领域模型：单份保单的完整提取结果"""

import json
from dataclasses import dataclass, field, asdict
from .insured_person import InsuredPerson


@dataclass
class ExtractionResult:
    """单份保单的完整提取结果"""
    file_name: str = ""
    insurance_company: str = ""
    policy_number: str = ""              # 自身保单号（主保单=主保单号；批单=批单号 71开头）
    main_policy_number: str = ""         # 2026-09-21 新增：批单关联的主保单号（"保险单号"标签）
    batch_policy_number: str = ""        # 2026-09-21 新增：批单号（"批单号"标签），主保单为空
    policy_type: str = ""                # 2026-09-21 新增："保单" / "批单"
    overall_start_date: str = ""
    overall_end_date: str = ""
    endorsement_effective_date: str = ""  # 2026-09-16 新增：批单生效日（"自X年Y月Z日零时起生效"）
    insured_persons: list[InsuredPerson] = field(default_factory=list)
    format_used: str = ""
    extraction_method: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        """稳定 JSON 输出（AGENTS.md 三重保险策略中的第 1 道）"""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_dict(self) -> dict:
        """转为 dict（供 LangGraph State 序列化）"""
        return asdict(self)

    def to_csv_rows(self) -> list[dict]:
        """扁平化行（CSV 导出）"""
        rows = []
        for person in self.insured_persons:
            rows.append({
                "姓名": person.name,
                "证件号码": person.id_number,
                "证件类型": person.id_type,
                "出生日期": person.birth_date,
                "所属公司": person.company,
                "批改类型": person.modification_type,
                "起始时间": person.start_date or self.overall_start_date,
                "起止时间": person.end_date or self.overall_end_date,
                "岗位名称": person.job_title,
                "保险公司": self.insurance_company,
                "保单号": self.policy_number,
                "来源文件": self.file_name,
            })
        return rows
