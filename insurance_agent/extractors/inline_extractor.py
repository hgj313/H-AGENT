"""Inline Extractor - 行内格式人员清单

适用多种 inline 格式：

格式1（利宝保险批单）：
    雇员姓名：张绍应，证件号：510223196903036833，方案序号：5，工种描述：砌筑工，
    用工单位：重庆选鹏建筑工程有限公司，保费计(CNY)：464.00；

格式2（粤灿批单）：
    雇员姓名：罗艳萍,证件类型：居民身份证,证件号码:522723196707242921,...,
    实际用工单位：广州市粤灿建设工程有限公司,...,批改生效日期:2026-06-25 00:00:00

支持批改类型识别：
- "增加雇员信息为" → 增保
- "删除雇员信息为" → 减保
- 无标记 → 默认增保
"""

import re
from insurance_agent.domain import InsuredPerson
from insurance_agent.tools import is_valid_chinese_id
from .base import BaseExtractor


class InlineExtractor(BaseExtractor):
    """行内格式提取器（批单类）

    支持多种 inline 格式，自动识别增保/减保。
    使用两步匹配：先定位"雇员姓名："，再在后续文本中查找身份证号。
    """

    # 增保标记
    _ADD_MARKERS = ["增加雇员信息为", "增加人员", "新增雇员", "批增"]
    # 减保标记
    _REMOVE_MARKERS = ["删除雇员信息为", "减少雇员信息为", "减少人员", "删除人员", "批减"]

    # 雇员姓名标记（用于分割记录）
    _NAME_MARKER = "雇员姓名"

    # 身份证号正则
    _ID_REGEX = re.compile(r"(\d{17}[\dXx])")

    # 姓名：2-4 个中文字符
    _NAME_REGEX = re.compile(r"[\u4e00-\u9fff]{2,4}")

    def extract(
        self,
        text: str,
        policy_holder: str = "",
        insurance_company: str = ""
    ) -> list[InsuredPerson]:
        persons = []
        if not text:
            return persons

        # 将文本按增保/减保标记分段
        segments = self._split_by_modification_type(text)

        for seg_text, mod_type in segments:
            seg_persons = self._extract_from_segment(seg_text, policy_holder, mod_type)
            persons.extend(seg_persons)

        return persons

    def _split_by_modification_type(self, text: str) -> list[tuple[str, str]]:
        """将文本按增保/减保标记分段

        Returns:
            [(segment_text, modification_type), ...]
            modification_type: "增保" or "减保"
        """
        # 找到所有标记位置
        markers = []  # [(position, type)]

        for marker in self._ADD_MARKERS:
            for m in re.finditer(re.escape(marker), text):
                markers.append((m.start(), "增保"))

        for marker in self._REMOVE_MARKERS:
            for m in re.finditer(re.escape(marker), text):
                markers.append((m.start(), "减保"))

        # 按位置排序
        markers.sort(key=lambda x: x[0])

        if not markers:
            # 无标记，整体为增保（默认）
            return [(text, "增保")]

        segments = []
        for i, (pos, mod_type) in enumerate(markers):
            seg_start = pos
            seg_end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
            segments.append((text[seg_start:seg_end], mod_type))

        return segments

    def _extract_from_segment(
        self, text: str, policy_holder: str, mod_type: str
    ) -> list[InsuredPerson]:
        """从一段文本中提取人员信息

        策略：按"雇员姓名"分割，每段找一个身份证号。
        """
        persons = []

        # 按"雇员姓名"分割文本
        parts = text.split(self._NAME_MARKER)
        # parts[0] 是标记前的文本（通常无用），跳过

        for part in parts[1:]:
            # part 的格式：：NAME, ... 证件号码:ID ... (到下一条记录)
            # 去掉开头的冒号和空白
            part = part.lstrip("：: \t\n\r")

            # 提取姓名（开头的中文字符）
            name_match = self._NAME_REGEX.match(part)
            if not name_match:
                continue
            name = name_match.group(0)

            # 在剩余文本中查找身份证号
            rest = part[name_match.end():]
            id_match = self._ID_REGEX.search(rest)
            if not id_match:
                continue
            raw_id = id_match.group(1)

            if not is_valid_chinese_id(raw_id):
                continue

            # tail = 从身份证号之后到下一条记录的文本
            tail = rest[id_match.end():]

            # 提取用工单位
            company = self._extract_company(tail, policy_holder)

            # 提取工种描述
            job_title = self._extract_job_title(tail)

            # 提取批改生效日期
            start_date = self._extract_effective_date(tail)

            persons.append(InsuredPerson(
                name=name,
                id_number=raw_id.strip().upper(),
                id_type="身份证",
                company=company,
                start_date=start_date,
                end_date="",
                job_title=job_title,
                confidence=0.9,
                modification_type=mod_type,
            ))

        return persons

    @staticmethod
    def _extract_company(tail: str, policy_holder: str = "") -> str:
        """从记录尾部提取用工单位（支持多种标签名）"""
        # 尝试多种用工单位标签
        company_patterns = [
            r"实际用工单位[：:]\s*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
            r"用工单位[：:]\s*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
            r"单位名称[：:]\s*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
        ]
        for pattern in company_patterns:
            m = re.search(pattern, tail)
            if m:
                return m.group(1)

        return policy_holder

    @staticmethod
    def _extract_job_title(tail: str) -> str:
        """从记录尾部提取工种描述"""
        # 尝试多种工种标签 — 匹配中文字符（含跨行连接）
        job_patterns = [
            r"工种描述[：:]\s*([\u4e00-\u9fff]+(?:\n[\u4e00-\u9fff]+)*)",
            r"职业工种名称[：:]\s*([\u4e00-\u9fff]+(?:\n[\u4e00-\u9fff]+)*)",
            r"职业(?:类别)?[：:]\s*([\u4e00-\u9fff]+(?:\n[\u4e00-\u9fff]+)*)",
        ]
        for pattern in job_patterns:
            m = re.search(pattern, tail)
            if m:
                # 工种名称可能跨行，去除换行符连接
                title = m.group(1).replace("\n", "").strip()
                if len(title) >= 2:
                    return title

        return ""

    @staticmethod
    def _extract_effective_date(tail: str) -> str:
        """从记录尾部提取批改生效日期"""
        # 尝试多种日期标签
        date_patterns = [
            r"批改生效日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})",
            r"生效日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})",
            r"起期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})",
        ]
        for pattern in date_patterns:
            m = re.search(pattern, tail)
            if m:
                date_str = m.group(1)
                # 归一化日期格式为 YYYY-MM-DD
                date_str = re.sub(r"[年/]", "-", date_str)
                date_str = re.sub(r"[月日]", "", date_str)
                # 补零
                parts = date_str.split("-")
                if len(parts) == 3:
                    return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                return date_str

        return ""
