"""保单文件库 (Policy Library)

功能：
- 存储上传的保单 PDF 文件（复制到统一目录）
- 建立索引：policy_number → metadata
- 支持按保单号查找主保单
- 支持按公司名模糊匹配查找主保单
- 批单处理时，通过保单号或公司名查找主保单，补全起止时间

索引存储：JSON 文件 (policy_library/index.json)
文件存储：policy_library/ 目录
"""

import json
import os
import shutil
from typing import Optional
from dataclasses import dataclass, field, asdict


@dataclass
class PolicyRecord:
    """保单库中的一条记录"""
    file_name: str = ""
    file_path: str = ""              # 原始文件路径
    stored_path: str = ""            # 库内存储路径
    policy_type: str = ""            # "保单" / "批单"
    policy_number: str = ""          # 保单号
    company: str = ""                # 所属公司（投保人）
    insurance_company: str = ""      # 保险公司
    start_date: str = ""             # 保险起始时间
    end_date: str = ""               # 保险起止时间
    persons_count: int = 0           # 人员数量
    persons: list[dict] = field(default_factory=list)  # 人员清单（精简）


class PolicyLibrary:
    """保单文件库

    使用方式：
        lib = PolicyLibrary(base_dir="C:/insurance-automation/policy_library")
        lib.register(result_dict)  # 注册提取结果
        main_policy = lib.find_main_policy("X44061701260000083506")
    """

    def __init__(self, base_dir: str = ""):
        self._base_dir = base_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "policy_library",
        )
        self._index_path = os.path.join(self._base_dir, "index.json")
        self._records: list[PolicyRecord] = []
        self._load()

    @property
    def base_dir(self) -> str:
        return self._base_dir

    @property
    def records(self) -> list[PolicyRecord]:
        return list(self._records)

    def register(self, result_dict: dict) -> PolicyRecord:
        """注册一条提取结果到保单库

        Args:
            result_dict: Agent 提取结果 dict

        Returns:
            PolicyRecord: 注册后的记录
        """
        from insurance_agent.tools import parse_policy_filename

        file_name = result_dict.get("file_name", "")
        file_path = result_dict.get("file_path", "")
        policy_number = result_dict.get("policy_number", "")
        insurance_company = result_dict.get("insurance_company", "")
        overall_start = result_dict.get("overall_start_date") or ""
        overall_end = result_dict.get("overall_end_date") or ""
        persons = result_dict.get("insured_persons", [])

        # 从文件名解析保单类型和公司名
        fname_info = parse_policy_filename(file_name)
        policy_type = fname_info.policy_type

        # 如果文件名没解析出类型，从内容推断
        if not policy_type:
            if any(p.get("modification_type") == "减保" for p in persons):
                policy_type = "批单"
            else:
                policy_type = "保单"

        # 公司名优先用提取结果中的投保人，其次用文件名中的
        company = result_dict.get("policy_holder", "") or fname_info.company

        # 精简人员列表（只存关键字段）
        persons_slim = [
            {
                "name": p.get("name", ""),
                "id_number": p.get("id_number", ""),
                "modification_type": p.get("modification_type", ""),
            }
            for p in persons
        ]

        record = PolicyRecord(
            file_name=file_name,
            file_path=file_path,
            stored_path="",
            policy_type=policy_type,
            policy_number=policy_number,
            company=company,
            insurance_company=insurance_company,
            start_date=overall_start,
            end_date=overall_end,
            persons_count=len(persons),
            persons=persons_slim,
        )

        # 如果有原始文件路径，复制到库内
        if file_path and os.path.exists(file_path):
            stored_name = file_name
            stored_path = os.path.join(self._base_dir, stored_name)
            if not os.path.exists(stored_path):
                try:
                    os.makedirs(self._base_dir, exist_ok=True)
                    shutil.copy2(file_path, stored_path)
                    record.stored_path = stored_path
                except Exception:
                    record.stored_path = file_path
            else:
                record.stored_path = stored_path

        # 更新或添加记录（按 file_name 去重）
        existing_idx = None
        for i, r in enumerate(self._records):
            if r.file_name == file_name:
                existing_idx = i
                break

        if existing_idx is not None:
            self._records[existing_idx] = record
        else:
            self._records.append(record)

        self._save()
        return record

    def find_main_policy_by_number(self, policy_number: str) -> Optional[PolicyRecord]:
        """通过保单号查找主保单（保单类型）

        批单文件中会包含主保单的保单号，
        用该保单号查找库中的保单类型记录。
        """
        if not policy_number:
            return None

        for r in self._records:
            if r.policy_type == "保单" and r.policy_number == policy_number:
                return r

        return None

    def find_main_policy_by_company(self, company: str) -> Optional[PolicyRecord]:
        """通过公司名模糊匹配查找主保单

        当批单未找到保单号匹配时，用公司名进行模糊匹配。
        """
        if not company:
            return None

        # 标准化公司名
        company_clean = company.replace("有限公司", "").replace("公司", "").strip()

        for r in self._records:
            if r.policy_type != "保单":
                continue
            r_company_clean = r.company.replace("有限公司", "").replace("公司", "").strip()
            # 双向包含匹配
            if company_clean and r_company_clean:
                if company_clean in r_company_clean or r_company_clean in company_clean:
                    return r

        return None

    @staticmethod
    def _policy_numbers_compatible(batch_no: str, main_no: str) -> bool:
        """检查批单保单号与主保单保单号是否兼容（同属一份保单）

        利宝规则：主保单 81XXXXXXXXXXXXXXXXXXYY / 批单 71XXXXXXXXXXXXXXXXXXNN
        → 第 1 位 8 vs 7（保单 vs 批单），第 2 位相同
        → 中间 18 位（positions 3-20，0-indexed 2..19）相同
        → 最后 1-2 位是流水号

        其它保险公司保单号结构不同 → 退化为：号码本身完全相等或共享长前缀
        （保守策略：前缀不一致时拒绝，避免错配）
        """
        if not batch_no or not main_no:
            return False
        if batch_no == main_no:
            return True
        # 利宝：8 vs 7 + 共享中段
        if len(batch_no) >= 20 and len(main_no) >= 20:
            # 第 2 位（index 1）必须相同
            if batch_no[1] != main_no[1]:
                return False
            # 中段 positions 2..19（18 位）必须完全一致
            if batch_no[2:20] == main_no[2:20]:
                # 利宝第 1 位 8=主保单 / 7=批单
                if batch_no[0] == "7" and main_no[0] == "8":
                    return True
                # 其它保险公司（保单号首字符非 7/8）：保守按"前 18 位相同"放行
                if batch_no[0] not in ("7", "8") and main_no[0] not in ("7", "8"):
                    return True
        return False

    def find_main_policy(
        self, policy_number: str = "", company: str = ""
    ) -> Optional[PolicyRecord]:
        """查找主保单：先按保单号，再按公司名（带保单号前缀兼容性校验）

        Args:
            policy_number: 批单中的保单号（同时用于保单号前缀兼容性校验）
            company: 公司名称（备用匹配）

        Returns:
            PolicyRecord or None

        Note:
            2026-09-15 加固：仅按公司名模糊匹配时，必须校验保单号前缀兼容
            （否则森炜 0072423000 批单会匹配到 6894300 主保单，把别人的起止日期
            错填到本批单的逐人记录中）。
        """
        # 1. 先按保单号精确匹配
        if policy_number:
            record = self.find_main_policy_by_number(policy_number)
            if record:
                return record

        # 2. 再按公司名模糊匹配（带保单号前缀兼容性校验）
        if company:
            record = self.find_main_policy_by_company(company)
            if record and policy_number:
                # 校验保单号前缀是否兼容：拒绝"同公司不同保单号"的错配
                if not self._policy_numbers_compatible(policy_number, record.policy_number):
                    return None
            return record

        return None

    def _load(self):
        """从 JSON 文件加载索引"""
        if os.path.exists(self._index_path):
            try:
                with open(self._index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._records = [PolicyRecord(**r) for r in data.get("records", [])]
            except Exception:
                self._records = []
        else:
            self._records = []

    def _save(self):
        """保存索引到 JSON 文件"""
        os.makedirs(self._base_dir, exist_ok=True)
        data = {
            "records": [asdict(r) for r in self._records],
        }
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        main_count = sum(1 for r in self._records if r.policy_type == "保单")
        batch_count = sum(1 for r in self._records if r.policy_type == "批单")
        return f"PolicyLibrary(records={len(self._records)}, 保单={main_count}, 批单={batch_count})"
