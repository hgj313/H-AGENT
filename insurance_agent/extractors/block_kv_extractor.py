"""BlockKV Extractor - 块状键值对清单提取器（2026-09-17 新增）

适用格式（中国人寿"在保名单"绿洲团体意外险等）：

    有效被保险人清单
    投保人名称：重庆吉盛生态园林绿化有限公司
    保险合同满期日期：2027-05-21
    保险合同生效日期：2026-05-22
    汇交号/保险合同号：2026660531D7H400052298
    险种名称：险种1、国寿新绿洲团体意外伤害保险（A款）
    投保人数：29
    有效被保人数：26

    序  号：1 姓名：刘典斌
    被保人类型：主被保险人
    主被保人顺序号：1
    性别：男
    出生日期：1971-06-18
    学号/工号：-
    证件 类型 及号 码：身份 证:42108119710618563X
    职业名称：电路安装及维修工人
    属组名称：1
    生效日期：2026-05-22 终止日期：2027-05-21
    要约状态：生效
    险种1 保额: 400000元   险种2 保额: 40000元

    序  号：2 姓名：徐兵
    ...

特点：
- 每个人是一个"键值对块"，不是真正的表格
- 每人有独立的"生效日期"和"终止日期"（**逐人日期**，与中国人寿财险整体期限不同）
- PDF 文本含大量跨行干扰（"身份\n证" / "序\n号" / "打\n印\n人"），需要先清理
- 保单号格式："汇交号/保险合同号"+"22 位"（中国人寿绿洲团体意外险常见）

与 existing 格式区分：
- table：标准表格，有"序号/姓名/身份证"等列
- inline：利宝批单"雇员姓名：X，证件号：Y，用工单位：Z" 行内替换
- individual：单人保单（人保关爱保），被保险人信息键值对
- block_kv：多人清单，每人一个块状键值对（**新增**）
"""

import re
from typing import Optional
from insurance_agent.domain import InsuredPerson
from insurance_agent.tools import is_valid_chinese_id
from .base import BaseExtractor


class BlockKVExtractor(BaseExtractor):
    """块状键值对清单提取器（中国人寿"在保名单"等）

    核心策略：按"姓名："分块，每块内提取该人员的字段。
    避免用单个 DOTALL 正则跨块匹配——那样会把 A 的姓名和 B 的身份证错配。
    """

    # 特征标记（"在保名单" / "有效被保险人清单" 是中国人寿绿洲团体意外险典型特征）
    _LIST_MARKERS = [
        "有效被保险人清单",
        "被保险人清单",
        "在保名单",
    ]

    # 每块起始：姓名：xxx
    _NAME_START_PATTERN = re.compile(r"姓名[：:]\s*([\u4e00-\u9fff]{2,4})")

    # 18 位身份证号
    _ID_NUMBER_PATTERN = re.compile(r"(\d{17}[\dXx])")

    # 出生日期（终止到下一字段标签或人员块结束）
    # 2026-09-17 修复：原 regex 用 (\d{4}[-/年]\d{1,2}[-/月]\d{1,2}) 在某些格式下匹配失败；
    # 改为允许 [日]? 和可选 . ，并用非贪婪捕获
    _BIRTH_PATTERN = re.compile(
        r"出生日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})"
    )

    # 生效/终止日期（同一块内）
    _PERIOD_PATTERN = re.compile(
        r"生效日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})"
        r"\s*终止日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})"
    )

    # 性别
    _GENDER_PATTERN = re.compile(r"性别[：:]\s*([男女])")

    # 职业（捕获到下一个字段标签或文件末尾前）
    # 2026-09-17 修复：\S+ 会在跨行合并后的空格处截断（如"电路安装及维 修工人" → 只截到"电路安装及维"）。
    # 改为捕获到下一个字段标签或终止位置（属组名称/生效日期/要约状态等）。
    _JOB_PATTERN = re.compile(
        r"职业名称[：:]\s*"
        r"(.*?)"
        r"(?=\s*(?:属组名称|生效日期|要约状态|险种\d+|学号/工号|证件类型及号码|$))"
    )

    # 整体期限（兜底）
    # 注意：PDF 中"保险合同生效日期"和"保险合同满期日期"两条字段谁先谁后不固定，
    # 兼容两种顺序：生效→满期 或 满期→生效。
    # 必须用两个独立 regex 才能可靠处理——单条 regex 用非捕获组匹配会出现歧义。
    _OVERALL_PERIOD_PATTERNS = [
        # 顺序1：生效在前
        re.compile(
            r"保险合同生效日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})"
            r".*?保险合同满期日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})"
        ),
        # 顺序2：满期在前
        re.compile(
            r"保险合同满期日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})"
            r".*?保险合同生效日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})"
        ),
    ]

    @classmethod
    def is_match(cls, all_text: str) -> bool:
        """判断是否为块状键值对清单格式

        优先用强特征"汇交号/保险合同号"+ "有效被保险人清单"，弱特征"在保名单"。
        """
        if "有效被保险人清单" in all_text:
            return True
        if "汇交号" in all_text and "保险合同号" in all_text:
            return True
        if "被保人顺序号" in all_text and "要约状态" in all_text:
            # 绿洲团体意外险特征
            return True
        return False

    def extract(
        self,
        text: str,
        policy_holder: str = "",
        insurance_company: str = "",
    ) -> list[InsuredPerson]:
        """从文本中提取被保险人清单"""
        if not text:
            return []

        # 1. 文本清理（跨行合并）
        clean_text = self._clean_text(text)

        # 2. 提取整体期限（兜底）
        overall_start, overall_end = self._extract_overall_period(clean_text)

        # 3. 按"姓名："分块，逐人提取
        chunks = re.split(r"姓名[：:]\s*", clean_text)
        persons: list[InsuredPerson] = []

        for chunk in chunks[1:]:  # 跳过第一个 chunk（抬头）
            person = self._parse_person_chunk(chunk, policy_holder, overall_start, overall_end)
            if person:
                persons.append(person)

        return persons

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理 PDF 跨行干扰

        - "身份\n证" → "身份证"
        - "序\n号" → "序号"
        - "证件\n类型\n及号\n码：" → "证件类型及号码："
        - 多空白合并为单空格
        """
        # 身份 证（含跨行/多空格）→ 身份证
        text = re.sub(r"身份\s*\n?\s*证", "身份证", text)
        # 证件类型及号码（含跨行/多空格 + 冒号）
        text = re.sub(r"证\s*件\s*类\s*型\s*及\s*号\s*码\s*[:：]?", "证件类型及号码：", text)
        # 序号：合并跨行（如"序\n号：12"）
        text = re.sub(r"序\s*号\s*[:：]\s*\n?\s*(\d+)", r"序号:\1", text)
        # 序号：合并数字+换行（如"序\n号：\n12"）
        text = re.sub(r"序\s*号\s*[:：]?\s*\n\s*(\d+)", r"序号:\1", text)
        # 打印人/日期等水印内容太多会干扰，统一去除换行但不删除字符
        text = re.sub(r"打印人[：:]\s*\S+", "", text)
        # 多空白合并
        text = re.sub(r"\s+", " ", text)
        return text

    @classmethod
    def _extract_overall_period(cls, text: str) -> tuple[str, str]:
        """提取整体保险期间（兜底用）"""
        for pattern in cls._OVERALL_PERIOD_PATTERNS:
            m = pattern.search(text)
            if m:
                return (cls._normalize_date(m.group(1)), cls._normalize_date(m.group(2)))
        return ("", "")

    @classmethod
    def _parse_person_chunk(
        cls,
        chunk: str,
        policy_holder: str,
        overall_start: str,
        overall_end: str,
    ) -> Optional[InsuredPerson]:
        """解析单个人员块"""
        # 姓名（开头第一个 2-4 字中文）
        m = re.match(r"^([\u4e00-\u9fff]{2,4})", chunk.strip())
        if not m:
            return None
        name = m.group(1).strip()

        # 身份证
        m = cls._ID_NUMBER_PATTERN.search(chunk)
        if not m:
            return None
        id_number = m.group(1).strip().upper()
        if not is_valid_chinese_id(id_number):
            return None

        # 出生日期
        m = cls._BIRTH_PATTERN.search(chunk)
        birth_date = cls._normalize_date(m.group(1)) if m else ""
        if not birth_date and len(id_number) == 18:
            # 兜底：从身份证提取
            birth_date = f"{id_number[6:10]}-{id_number[10:12]}-{id_number[12:14]}"

        # 性别
        m = cls._GENDER_PATTERN.search(chunk)
        gender = m.group(1) if m else ""

        # 职业
        m = cls._JOB_PATTERN.search(chunk)
        job_title = m.group(1).strip() if m else ""

        # 逐人起止日期（**block_kv 格式的关键特征**）
        m = cls._PERIOD_PATTERN.search(chunk)
        if m:
            start_date = cls._normalize_date(m.group(1))
            end_date = cls._normalize_date(m.group(2))
        else:
            # 兜底用整体期限
            start_date = overall_start
            end_date = overall_end

        return InsuredPerson(
            name=name,
            id_number=id_number,
            id_type="身份证",
            birth_date=birth_date,
            company=policy_holder,
            start_date=start_date,
            end_date=end_date,
            job_title=job_title,
            confidence=0.92,
            modification_type="增保",
        )

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """将 'YYYY-MM-DD' / 'YYYY/MM/DD' / 'YYYY年M月D日' 规范成 'YYYY-MM-DD'"""
        if not date_str:
            return ""
        s = re.sub(r"[年/]", "-", date_str)
        s = re.sub(r"[月日]", "", s)
        parts = s.split("-")
        if len(parts) != 3:
            return date_str
        return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
