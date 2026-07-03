"""Table Extractor - 表格格式人员清单

适用格式（如太平洋保险雇员清单）：
    序号 | 姓名 | 证件类型 | 证件号码 | 岗位名称 | 起期 | 止期
    1    | 李刚 | 身份证  | 512528197612124918 | 钢结构安装工 | 2026-06-24 | 2026-09-24
"""

import re
from insurance_agent.domain import InsuredPerson
from insurance_agent.tools import (
    extract_chinese_id_from_text,
    extract_names_near,
    extract_dates_near,
    extract_company_name,
)
from .base import BaseExtractor


class TableExtractor(BaseExtractor):
    """表格格式提取器

    策略：先用身份证号定位"人"的位置，再从上下文提取姓名/日期/公司/工种
    """

    # 常见工种模式（用于在上下文里捕获岗位名称）
    _JOB_PATTERN = re.compile(
        r"([\u4e00-\u9fff]{2,10}(?:工|员|师|者|人))"
    )

    def extract(
        self,
        text: str,
        policy_holder: str = "",
        insurance_company: str = ""
    ) -> list[InsuredPerson]:
        persons = []
        if not text:
            return persons

        # 只在 "人员清单" 标记之后搜索
        list_markers = ["人员清单", "雇员清单", "被保险人清单", "员工清单"]
        list_text = text
        for marker in list_markers:
            idx = text.find(marker)
            if idx >= 0:
                list_text = text[idx:]
                break

        # 1. 定位所有合法身份证号
        valid_ids = extract_chinese_id_from_text(list_text)
        if not valid_ids:
            return persons

        # 2. 找到每个身份证号在 list_text 中的位置
        for id_number in valid_ids:
            id_pos = list_text.find(id_number)
            if id_pos < 0:
                continue

            # 3. 在身份证号附近提取姓名
            name_candidates = extract_names_near(list_text, id_pos, window=200)
            name = name_candidates[-1] if name_candidates else ""

            # 4. 在身份证号附近提取日期
            dates = extract_dates_near(list_text, id_pos, window=400)
            start_date = dates[0] if len(dates) >= 1 else ""
            end_date = dates[1] if len(dates) >= 2 else ""

            # 5. 在身份证号附近提取公司名 / 用工单位
            company = ""
            # 优先用工单位标签
            post_region = list_text[id_pos:id_pos + 400]
            m_company = re.search(
                r"用工单位[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
                post_region
            )
            if m_company:
                company = m_company.group(1)
            else:
                company_match = extract_company_name(post_region)
                if company_match:
                    company = company_match
                elif policy_holder:
                    company = policy_holder

            # 6. 在身份证号附近提取工种
            job_title = ""
            job_match = self._JOB_PATTERN.search(post_region)
            if job_match:
                job_title = job_match.group(1)

            persons.append(InsuredPerson(
                name=name,
                id_number=id_number,
                id_type="身份证",
                company=company,
                start_date=start_date,
                end_date=end_date,
                job_title=job_title,
                confidence=0.85,
            ))

        return persons
