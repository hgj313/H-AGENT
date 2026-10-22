# -*- coding: utf-8 -*-
r"""申能财产保险（雇主责任保险 2026 版）提取回归测试

背景（2026-09-28）：重庆阙光不锈钢制品有限公司保单
  - 保单号 6513630150160260000001（20 位纯数字）
  - 保险期间 "自北京时间2026年03月06日0时起至2027年03月05日24时止"
  - 雇员清单跨 2 页（Page 3 首 5 人 + Page 4 续 4 人，续页无表头）
  - 身份证 14+4 脱敏格式 `51302219740317****`
  - 工种跨行 `金属炊具及\n器皿制作工`

初始适配零代码复用（14+4 脱敏 / 跨行工种合并 / 清单续页识别均已支持），
但日期全为 NULL —— 根因是 date_parser 的整体期间正则要求"自"后紧跟年份，
而本保单在"自"与年份之间插入了"北京时间"四个字。
修复见 tests/test_date_parser_timezone_prefix.py。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf  # noqa: E402

from insurance_agent.extractors.table_extractor import TableExtractor  # noqa: E402
from insurance_agent.tools.date_parser import extract_overall_insurance_period  # noqa: E402

PDF_PATH = r"C:\Users\Administrator\Downloads\吴祖华保险.pdf"

POLICY_NUMBER = "6513630150160260000001"
EXPECTED_PERIOD = ("2026-03-06", "2027-03-05")
EXPECTED_COMPANY = "重庆阙光不锈钢制品有限公司"
EXPECTED_JOB = "金属炊具及器皿制作工"

# 清单所在页（0-based）：Page 2 雇员清单表头 + 前 5 人；Page 3 续页 4 人（无表头）
# 注意：条款页（Page 4/10/11）含"注册号：6230912026..."，绝不能混进清单文本
LIST_PAGE_INDEXES = (1, 2)

# 9 人（按保单清单顺序）+ 14+4 脱敏身份证
EXPECTED_PERSONS = [
    ("石章勇", "51302219740317****"),
    ("张和清", "51022619710525****"),
    ("余立校", "51232319720117****"),
    ("杨帮华", "51232319710129****"),
    ("申学建", "50023919841004****"),
    ("杨光灿", "50011319960314****"),
    ("杨淋", "51022119740226****"),
    ("邓昌平", "51122419830601****"),
    ("刘贵华", "51022219731129****"),
]


def _full_text():
    doc = pymupdf.open(PDF_PATH)
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _list_pages_text():
    """只取清单页（Page 3 / Page 4）文本 —— 复刻 personnel_extractor_node 的真实输入

    ⚠️ 不要用全文喂 TableExtractor：11 页保单的条款页（Page 4/10/11）含
    "注册号：6230912026..."（18 位数字被当身份证），全文本直喂会多出 3 个垃圾人
    （name='注册号'）。生产 pipeline 只传 list_pages，所以线上无此问题 ——
    本测试刻意保持与线上一致，防止"为了测试好写"而放宽断言掩盖真实链路差异。
    """
    doc = pymupdf.open(PDF_PATH)
    try:
        return "".join(doc[i].get_text() for i in LIST_PAGE_INDEXES)
    finally:
        doc.close()


def test_overall_period_with_timezone_prefix():
    """"自北京时间X起至Y止" 必须能解析出整体期间（本次修复核心断言）"""
    assert extract_overall_insurance_period(_full_text()) == EXPECTED_PERIOD


def test_company_prefix_fallback():
    from insurance_agent.tools.company_extractor import detect_insurance_company_by_policy_number

    assert detect_insurance_company_by_policy_number(POLICY_NUMBER) == "申能财产保险"


def test_extract_9_persons_with_masked_ids_and_merged_job():
    """清单提取：9 人 / 14+4 脱敏 ID / 跨行工种合并 / 跨页续页识别

    company 参数 = 投保人（复刻 personnel_extractor_node 的调用方式：
    `self._table.extract(text, policy_holder, insurance_company)`）。
    本保单清单页无"用工单位"列 → 用工单位由投保人兜底，故这里必须显式传。
    """
    persons = TableExtractor().extract(
        text=_list_pages_text(),
        policy_holder=EXPECTED_COMPANY,
        insurance_company="申能财产保险",
    )

    assert len(persons) == len(EXPECTED_PERSONS), f"人数不符: 实际 {len(persons)}"
    for (exp_name, exp_id), p in zip(EXPECTED_PERSONS, persons):
        assert p.name == exp_name, f"姓名不符: {p.name} != {exp_name}"
        assert p.id_number == exp_id, f"证件号不符: {p.id_number} != {exp_id}"
        assert p.job_title == EXPECTED_JOB, f"工种不符(跨行未合并): {p.job_title} != {EXPECTED_JOB}"
        assert p.company == EXPECTED_COMPANY, f"用工单位不符: {p.company} != {EXPECTED_COMPANY}"

    # 14+4 脱敏格式必须保留 * 号，不反推
    assert all("*" in p.id_number for p in persons)


def test_no_person_carries_overall_dates():
    """清单页无逐人日期 → 每人 start/end 应为空，交由 validator 用整体期间兜底

    （如果这里被填了具体日期，说明 extractor 开始跨行误抓日期，是回归信号）
    """
    for p in TableExtractor().extract(text=_list_pages_text()):
        assert p.start_date in (None, ""), f"{p.name} 意外带上起始日期 {p.start_date}"
        assert p.end_date in (None, ""), f"{p.name} 意外带上结束日期 {p.end_date}"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))