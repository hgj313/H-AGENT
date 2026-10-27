# -*- coding: utf-8 -*-
r"""平安产险「平安放心意外尊享方案(互联网版)」新格式适配回归测试

PDF: 浙江珩瑞装饰工程有限公司(1)(1)(1).pdf
  - 保险公司: 中国平安财产保险股份有限公司
  - 产品: 平安放心意外尊享方案(互联网版)
  - 保单号: 13531006601399793363 (20 位)
  - 投保人/被保险人: 浙江珩瑞装饰工程有限公司
  - 保险期限: 2026年10月17日00时00分00秒 起 至 2027年10月16日24时00分00秒 止 (北京时间)

与既有"平安产险-雇主安心保-四川"是**不同产品线**，本格式有 5 处全新特征：

1. **第 4 种脱敏 ID 格式** `41**************16`（2 位省代码 + 14 星 + 2 位校验段）
   - 末位可能是 X（`34**************5X`）
   - ⚠️ 与"统一社会信用代码"（`91**************89`）格式完全相同 → 必须靠前置标签区分
2. **第 5 种整体期间格式**：无"自"字，裸日期 + "起 至"（中间可换行），时区在**末尾**
3. **清单标题**是"2、被保险人信息"（不含"名单/清单"字样）→ 需登记新 marker
4. **format_hint 误判**：`_is_individual_policy` 的三项判据全中 → 误走 individual 提取器 → 0 人
5. **脱敏 ID 撞车**：张超与蔡明明的脱敏 ID 完全相同（34**************18）
   → 旧唯一键 (id_number, policy_number) 会让后者覆盖前者 → 5 人只入库 4 人

5 人清单：
  胡银进 / 张超 / 张金虎 / 蔡臣飞 / 蔡明明
  工种统一为 "钢结构安装工"（"职业:钢结构安装工;" 内嵌在"其他信息"列）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf  # noqa: E402

from insurance_agent.extractors.table_extractor import TableExtractor  # noqa: E402
from insurance_agent.tools.date_parser import extract_overall_insurance_period  # noqa: E402
from insurance_agent.tools.id_validator import (  # noqa: E402
    extract_chinese_id_from_text,
    extract_chinese_id_with_positions,
    is_valid_chinese_id,
)

PDF_PATH = r"C:\Users\Administrator\Downloads\浙江珩瑞装饰工程有限公司(1)(1)(1).pdf"

POLICY_NUMBER = "13531006601399793363"
EXPECTED_PERIOD = ("2026-10-17", "2027-10-16")
EXPECTED_COMPANY = "浙江珩瑞装饰工程有限公司"
EXPECTED_JOB = "钢结构安装工"

EXPECTED_PERSONS = [
    ("胡银进", "41**************16"),
    ("张超", "34**************18"),
    ("张金虎", "34**************35"),
    ("蔡臣飞", "34**************5X"),
    ("蔡明明", "34**************18"),  # 与张超 ID 完全相同（脱敏撞车）
]


def _full_text():
    doc = pymupdf.open(PDF_PATH)
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _list_pages_text():
    """只取清单页（Page 1 / Page 2）—— 复刻 personnel_extractor_node 的真实输入

    ⚠️ 不要用全文喂 TableExtractor：本保单 Page 2 有"序号/特约内容"条款表，
    全文本直喂会把条款编号当清单内容。生产 pipeline 只传 list_pages。
    """
    doc = pymupdf.open(PDF_PATH)
    try:
        return "".join(doc[i].get_text() for i in (0, 1))
    finally:
        doc.close()


# ---------------- 1. 脱敏 ID 第 4 种格式 ----------------

def test_extract_5_masked_ids():
    """5 个脱敏 ID 全部提取，统一社会信用代码被排除"""
    ids = extract_chinese_id_from_text(_full_text())
    assert len(ids) == 5, f"应提取 5 个 ID，实际 {len(ids)}: {ids}"
    for _, exp_id in EXPECTED_PERSONS:
        assert exp_id in ids, f"缺少 {exp_id}"


def test_unified_social_credit_code_excluded():
    """投保人的统一社会信用代码（格式与身份证相同）必须被排除"""
    ids = extract_chinese_id_from_text(_full_text())
    assert "91**************89" not in ids, "统一社会信用代码被误当身份证"
    assert len(ids) == 5


def test_masked_id_with_trailing_x():
    """末位校验码为 X 的脱敏 ID 必须被识别"""
    assert is_valid_chinese_id("34**************5X")
    assert is_valid_chinese_id("41**************16")


def test_id_positions_keep_duplicates():
    """带位置的提取必须保留撞车的重复 ID（张超 / 蔡明明）"""
    with_pos = extract_chinese_id_with_positions(_full_text())
    assert len(with_pos) == 5, f"应保留 5 条（含撞车重复），实际 {len(with_pos)}"
    assert len({p for _, p in with_pos}) == 5, "位置应互不相同"
    assert len({i for i, _ in with_pos}) == 4, "去重后应只剩 4 个不同 ID（张超/蔡明明撞车）"


# ---------------- 2. 第 5 种整体期间格式 ----------------

def test_overall_period_bare_date_with_trailing_timezone():
    """"X年X月X日 起 至 Y年Y月Y日 止 (北京时间)" 必须能解析（无"自"字）"""
    assert extract_overall_insurance_period(_full_text()) == EXPECTED_PERIOD


def test_period_regression_legacy_formats():
    """历史格式不得回归"""
    cases = [
        ("保险期间：自2026年06月17日0时起至2026年09月16日24时止", ("2026-06-17", "2026-09-16")),
        ("保险期间：自北京时间2026年03月06日0时起至2027年03月05日24时止", ("2026-03-06", "2027-03-05")),
        ("保险起期（北京时间）：2026 年06 月20 日00 时 保险止期（北京时间）：2027 年06 月19 日24 时",
         ("2026-06-20", "2027-06-19")),
        ("保险期间：自 2026 年 10 月 01 日 零时起至 2027 年 10 月 01 日 24 时止", ("2026-10-01", "2027-10-01")),
    ]
    for text, expected in cases:
        assert extract_overall_insurance_period(text) == expected, f"回归: {text[:30]}"


# ---------------- 3. 清单页定位 + format_hint ----------------

def test_list_marker_registered():
    """"被保险人信息" 必须登记为清单 marker"""
    from insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node import _LIST_MARKERS

    assert "被保险人信息" in _LIST_MARKERS
    # ⚠️ "投保人信息"不能加 —— 那是投保人章节，会把无清单保单误判为有清单
    assert "投保人信息" not in _LIST_MARKERS


def test_not_misjudged_as_individual_policy():
    """表格型被保险人清单不能被误判为 individual（键值对）格式"""
    from insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node import MetadataExtractorNode

    node = MetadataExtractorNode()
    assert node._is_individual_policy(_full_text()) is False
    assert node._has_table_list_header(_full_text()) is True


def test_individual_policy_still_detected():
    """真正的个人保单（键值对）不能被误伤"""
    from insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node import MetadataExtractorNode

    node = MetadataExtractorNode()
    kv_text = (
        "某个人保单\n被保险人信息\n中文姓名：张三\n证件号码：110101199001011234\n"
        "被保险人姓名：李四\n身份证号：310101199203054321\n"
    )
    assert node._is_individual_policy(kv_text) is True

    # 条款正文里出现"序号"也不该误伤
    kv_text2 = (
        "被保险人信息\n中文姓名：王五\n证件号码：110101199001011234\n"
        "特别约定：\n序号 1 某某条款\n"
    )
    assert node._is_individual_policy(kv_text2) is True


# ---------------- 4. 清单提取 ----------------

def test_extract_5_persons_with_merged_job():
    """5 人 / 脱敏 ID / 工种 / 用工单位（投保人兜底）"""
    persons = TableExtractor().extract(
        text=_list_pages_text(),
        policy_holder=EXPECTED_COMPANY,
        insurance_company="中国平安",
    )
    assert len(persons) == 5, f"人数不符: 实际 {len(persons)}"
    for (exp_name, exp_id), p in zip(EXPECTED_PERSONS, persons):
        assert p.name == exp_name, f"姓名不符: {p.name} != {exp_name}"
        assert p.id_number == exp_id, f"证件号不符: {p.id_number} != {exp_id}"
        assert p.job_title == EXPECTED_JOB, f"工种不符: {p.job_title} != {EXPECTED_JOB}"
        assert p.company == EXPECTED_COMPANY, f"用工单位不符: {p.company} != {EXPECTED_COMPANY}"


def test_company_name_strips_table_header_prefix():
    """公司名前粘连的表头词必须被剥离（曾误得"手机号码浙江珩瑞装饰工程有限公司"）"""
    from insurance_agent.tools.company_extractor import _strip_table_header_prefix, extract_company_name

    assert _strip_table_header_prefix("手机号码浙江珩瑞装饰工程有限公司") == EXPECTED_COMPANY
    assert extract_company_name("手机号码\n浙江珩瑞装饰工程有限公司\n") == EXPECTED_COMPANY
    # 正常公司名不被破坏
    assert _strip_table_header_prefix(EXPECTED_COMPANY) == EXPECTED_COMPANY


# ---------------- 5. DB 唯一键（脱敏撞车） ----------------

def test_db_unique_key_includes_name():
    """唯一键必须含 name，否则撞车脱敏 ID 会让人员静默丢失"""
    import sqlite3
    from insurance_agent.infrastructure.database import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='insurance_personnel'")
        row = cur.fetchone()
        assert row and row[0], "insurance_personnel 表不存在"
        normalized = "".join(row[0].split())
        assert "UNIQUE(name,id_number,policy_number)" in normalized, (
            f"唯一键未包含 name: {normalized[-120:]}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))