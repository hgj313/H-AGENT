"""InsuredPerson - 领域模型：被保人员标准记录

标准字段（所有保险公司最终都归一化为这套字段）：
- name             姓名
- id_number        证件号码
- id_type          证件类型
- company          所属公司 / 用工单位
- start_date       起始时间 (YYYY-MM-DD)
- end_date         起止时间 (YYYY-MM-DD)
- job_title        岗位名称 / 工种
- occupation_class 职业类别 / 等级
- confidence       提取置信度
"""

from dataclasses import dataclass


@dataclass
class InsuredPerson:
    """被保人员标准记录"""
    name: str = ""
    id_number: str = ""
    id_type: str = "身份证"
    company: str = ""
    start_date: str = ""
    end_date: str = ""
    job_title: str = ""
    occupation_class: str = ""
    confidence: float = 0.0
