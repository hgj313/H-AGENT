"""Inline Extractor - 行内格式人员清单

适用格式（如利宝保险批单）：
    雇员姓名：张绍应，证件号：510223196903036833，方案序号：5，工种描述：砌筑工，
    用工单位：重庆选鹏建筑工程有限公司，保费计(CNY)：464.00；
"""

import re
from insurance_agent.domain import InsuredPerson
from insurance_agent.tools import is_valid_chinese_id
from .base import BaseExtractor


class InlineExtractor(BaseExtractor):
    """行内格式提取器（批单类）"""

    # 一条人员记录 = 雇员姓名：... 证件号：... ... ；
    _RECORD_PATTERN = re.compile(
        r"雇员姓名[：:]\s*([\u4e00-\u9fff]{2,4})\s*[，,]"
        r"\s*证件号[：:]\s*(\d{17}[\dXx])"
        r"(.*?)[；;]",
        re.DOTALL,
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

        for m in self._RECORD_PATTERN.finditer(text):
            name = m.group(1)
            raw_id = m.group(2)
            tail = m.group(3) or ""

            if not is_valid_chinese_id(raw_id):
                continue

            # 提取用工单位
            company = ""
            m_co = re.search(
                r"用工单位[：:]\s*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
                tail,
            )
            if m_co:
                company = m_co.group(1)
            elif policy_holder:
                company = policy_holder

            # 提取工种描述
            job_title = ""
            m_job = re.search(r"工种描述[：:]\s*([\u4e00-\u9fff]+)", tail)
            if m_job:
                job_title = m_job.group(1)

            persons.append(InsuredPerson(
                name=name,
                id_number=raw_id.strip().upper(),
                id_type="身份证",
                company=company,
                start_date="",   # 批单格式无逐人日期，由 metadata 兜底
                end_date="",
                job_title=job_title,
                confidence=0.9,
            ))

        return persons
