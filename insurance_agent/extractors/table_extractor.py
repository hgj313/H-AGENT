"""Table Extractor - 表格格式人员清单

适用格式（如太平洋保险雇员清单、中国人寿保单）：
    序号 | 姓名 | 证件类型 | 证件号码 | 岗位名称 | 起期 | 止期
    1    | 李刚 | 身份证  | 512528197612124918 | 钢结构安装工 | 2026-06-24 | 2026-09-24

也支持被保险人名单格式：
    序号 | 姓名 | 身份证号 | 职业类别 | 承保方案
    1    | 黄嗣彬 | 450802198506193118 | ... | 01

支持批改类型检测：
- 文本中出现"增加"/"批增" → 增保
- 文本中出现"删除"/"减少"/"批减" → 减保
- 默认 → 增保
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
    自动检测增保/减保标记。
    """

    # 常见工种模式（用于在上下文里捕获岗位名称）
    _JOB_PATTERN = re.compile(
        r"([\u4e00-\u9fff]{2,10}(?:工|员|师|者|人))"
    )

    # 工种误报黑名单（不是工种的词）
    _JOB_BLACKLIST = {
        "保险人", "投保人", "被保险人", "受益人", "经办人", "负责人",
        "联系人", "代理人", "证人", "签章人", "业务员",
    }

    # 减保标记
    _REMOVE_MARKERS = ["删除", "减少", "批减", "减保", "注销"]
    # 增保标记
    _ADD_MARKERS = ["增加", "新增", "批增", "增保"]

    def extract(
        self,
        text: str,
        policy_holder: str = "",
        insurance_company: str = ""
    ) -> list[InsuredPerson]:
        persons = []
        if not text:
            return persons

        # 检测批改类型
        mod_type = self._detect_modification_type(text)

        # 只在 "人员清单" 标记之后搜索
        list_markers = ["人员清单", "雇员清单", "雇员人名清单", "人名清单", "被保险人清单", "员工清单", "被保险人名单"]
        list_text = text
        for marker in list_markers:
            idx = text.find(marker)
            if idx >= 0:
                list_text = text[idx:]
                break

        # 预处理：合并 PDF 表格中跨行断开的内容
        # 1. 合并跨行身份证号: "4527251967\n0226048X" → "45272519670226048X"
        #    注意：前段要求≥3位数字，避免误伤日期时间文本
        #    （如"2026-04-03 00:00:00\n2026-09-10"里"00\n2"是时分秒，不应合并）
        list_text = re.sub(r'(\d{3,})\n(\d|[Xx])', r'\1\2', list_text)
        # 2. 合并跨行公司名: "广州市粤灿建设工程有限\n公司" → "广州市粤灿建设工程有限公司"
        list_text = re.sub(r'([\u4e00-\u9fff])\n(公司|集团|股份|责任)', r'\1\2', list_text)
        # 3. 去除"制单时间"页脚噪声（含日期，会干扰每人起止日期提取）
        #    例: "制单时间：2026年03月23日15时16分12秒"
        list_text = re.sub(r'制单时间[：:]\s*\d{4}[年\-]\d{1,2}[月\-]\d{1,2}[^\n]*', '', list_text)
        # 4. 合并跨行工种（表格单元格内换行）:
        #    例: "起重装卸机械\n操作工（吊车\n）" → "起重装卸机械操作工（吊车）"
        #    4a. 先合并括号跨行 "吊车\n）" → "吊车）"
        list_text = re.sub(r'([\u4e00-\u9fff（])\n(）)', r'\1\2', list_text)
        #    4b. 再合并工种主体跨行 "机械\n操作工" → "机械操作工"
        #        （后一行须以工/员/师/者/人结尾，且排除"雇员/员工/人员"等表头词，避免误合并表头）
        list_text = re.sub(
            r'([\u4e00-\u9fff])\n((?!雇员|员工|人员)[\u4e00-\u9fff]{1,8}(?:工|员|师|者|人))',
            r'\1\2',
            list_text,
        )

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

            # 3.5 从身份证号中提取出生日期（第7-14位 YYYYMMDD）
            birth_date = ""
            if len(id_number) >= 14:
                birth_year = id_number[6:10]
                birth_month = id_number[10:12]
                birth_day = id_number[12:14]
                birth_date = f"{birth_year}-{birth_month}-{birth_day}"

            # 身份证号之后的文本（表格中起止日期/工种/公司都在证件号之后）
            post_region = list_text[id_pos:id_pos + 400]

            # 4. 在身份证号之后提取日期（只取证件号之后，避免混入前一人日期）
            # 出生日期通常年份 < 2010，保险起止日期通常在 2020 年代
            dates = [
                d for d in extract_dates_near(post_region, 0, window=400)
                if d != birth_date and int(d[:4]) >= 2010
            ]
            start_date = dates[0] if len(dates) >= 1 else ""
            end_date = dates[1] if len(dates) >= 2 else ""
            # 兜底：起始时间晚于起止时间（识别反了）时交换
            if start_date and end_date and start_date > end_date:
                start_date, end_date = end_date, start_date

            # 5. 在身份证号附近提取公司名 / 用工单位
            company = ""
            # 优先用工单位标签
            m_company = re.search(
                r"(?:实际)?用工单位[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
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
            for job_match in self._JOB_PATTERN.finditer(post_region):
                candidate = job_match.group(1)
                if candidate not in self._JOB_BLACKLIST:
                    job_title = candidate
                    break

            persons.append(InsuredPerson(
                name=name,
                id_number=id_number,
                id_type="身份证",
                company=company,
                start_date=start_date,
                end_date=end_date,
                job_title=job_title,
                birth_date=birth_date,
                confidence=0.85,
                modification_type=mod_type,
            ))

        return persons

    @classmethod
    def _detect_modification_type(cls, text: str) -> str:
        """从文本中检测批改类型"""
        for marker in cls._REMOVE_MARKERS:
            if marker in text:
                return "减保"
        for marker in cls._ADD_MARKERS:
            if marker in text:
                return "增保"
        return "增保"
