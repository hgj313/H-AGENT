# -*- coding: utf-8 -*-
"""扫描件版面元数据 OCR —— 回归测试

背景（2026-11-13）：
    扫描件没有文字层 → metadata_extractor 的保单号 / 保险期间全取自
    PyMuPDF 文字层 → 两者皆空 → 人员 start_date/end_date 为空、
    policy_number 为空 → 无法关联主保单回填 → 闭环断裂。

本测试覆盖：
    1. 日期归一化（多种中文/ISO 写法）
    2. 保单号格式校验
    3. 从 OCR 原文兜底找保单号（必须优先于身份证号）
    4. 元数据归一化（OCR 值优先，规则兜底）
    5. extract_overall_metadata（mock LLM）
    6. PersonnelExtractorNode 集成：扫描件人员的日期被自动填充
"""

import base64
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from insurance_agent.extractors.ocr_extractor import (  # noqa: E402
    OCRExtractor,
    _looks_like_policy_number,
)
from insurance_agent.agents.invoice_recognition.nodes.personnel_extractor_node import (  # noqa: E402
    PersonnelExtractorNode,
)
from insurance_agent.domain import InsuredPerson  # noqa: E402


# ------------------------------------------------------------------ 1. 日期归一化

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026年10月01日", "2026-10-01"),
        ("2026 年 10 月 01 日", "2026-10-01"),
        ("2026-10-01", "2026-10-01"),
        ("2026/10/01", "2026-10-01"),
        ("2026.10.01", "2026-10-01"),
        ("保险期间自2026年10月1日起", "2026-10-01"),
        ("", ""),
        ("不是日期", ""),
    ],
)
def test_normalize_date_formats(raw, expected):
    assert OCRExtractor._normalize_date(raw) == expected


# ------------------------------------------------------------------ 2. 保单号校验

@pytest.mark.parametrize(
    "value, ok",
    [
        ("6130104121920260000000182", True),
        ("662290212192026BZN00000765", True),
        ("8116013100260058791000", True),
        ("保险单号：", False),          # 带标签
        ("123", False),                 # 太短
        ("", False),
    ],
)
def test_looks_like_policy_number(value, ok):
    assert _looks_like_policy_number(value) is ok


# ------------------------------------------------------------------ 3. 原文兜底找保单号

def test_find_policy_number_prefers_longer_policy_number_over_id_card():
    """保单号（22 位）必须优先于同页出现的身份证号（18 位）"""
    text = (
        "保险单号: 6130104121920260000000182 "
        "姓名 陈强 身份证号 370303198007313110 "
        "被保险人人数 11950人"
    )
    assert OCRExtractor._find_policy_number_in_text(text) == "6130104121920260000000182"


def test_find_policy_number_ignores_short_numbers():
    """年份、金额等短数字串不应被误当成保单号"""
    text = "保险期间 2026年10月 保费 800000.00 保单号 8116013100260058791000"
    assert OCRExtractor._find_policy_number_in_text(text) == "8116013100260058791000"


# ------------------------------------------------------------------ 4. 元数据归一化

def test_normalize_metadata_uses_ocr_values():
    merged = {
        "policy_number": "6130104121920260000000182",
        "overall_start_date": "2026-10-01",
        "overall_end_date": "2026-10-31",
        "insurance_company": "黄河财产保险股份有限公司",
        "total_persons": "11950",
    }
    out = OCRExtractor._normalize_metadata(merged, ['{"x":1}'])
    assert out["policy_number"] == "6130104121920260000000182"
    assert out["overall_start_date"] == "2026-10-01"
    assert out["overall_end_date"] == "2026-10-31"
    assert out["insurance_company"] == "黄河财产保险股份有限公司"


def test_normalize_metadata_falls_back_to_rule_when_ocr_dates_missing():
    """OCR 没给出日期时，用既有规则从 OCR 原文解析保险期间"""
    raw = "保险期间 31天，自2026年10月01日零时起，至2026年10月31日二十四时止。"
    out = OCRExtractor._normalize_metadata({}, [raw])
    assert out["overall_start_date"] == "2026-10-01"
    assert out["overall_end_date"] == "2026-10-31"


def test_normalize_metadata_falls_back_to_text_for_policy_number():
    raw = '{"note":"保险单号 6130104121920260000000182"}'
    out = OCRExtractor._normalize_metadata({"policy_number": "保险单号"}, [raw])
    assert out["policy_number"] == "6130104121920260000000182"


# ------------------------------------------------------------------ 5. extract_overall_metadata

class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """最小 LLM 替身：按调用顺序返回预设内容"""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        content = self._contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return _FakeResponse(content)


def test_extract_overall_metadata_reads_home_page():
    llm = _FakeLLM([
        '{"policy_number":"6130104121920260000000182",'
        '"overall_start_date":"2026-10-01","overall_end_date":"2026-10-31",'
        '"insurance_company":"黄河财产保险股份有限公司","total_persons":"11950"}'
    ])
    ex = OCRExtractor(llm_client=llm)
    meta = ex.extract_overall_metadata(page_images=["ZmFrZQ=="], max_pages=1)

    assert meta["policy_number"] == "6130104121920260000000182"
    assert meta["overall_start_date"] == "2026-10-01"
    assert meta["overall_end_date"] == "2026-10-31"
    assert meta["total_persons"] == "11950"
    assert llm.calls == 1


def test_extract_overall_metadata_cross_page_vote_picks_majority():
    """两页保单号不一致时按多数票采纳，并标记冲突"""
    llm = _FakeLLM([
        '{"policy_number":"6130104121920260000000182"}',   # 第 1 页（首页）
        '{"policy_number":"6130104121920260000000182"}',   # 第 2 页
    ])
    ex = OCRExtractor(llm_client=llm)
    meta = ex.extract_overall_metadata(page_images=["a", "b"], max_pages=2)
    assert meta["policy_number"] == "6130104121920260000000182"
    assert meta["policy_number_conflict"] is False
    assert llm.calls == 2


def test_extract_overall_metadata_flags_conflict_when_pages_disagree():
    """两页保单号不一致（模型把数字读错一位）→ 标记冲突并采纳多数票"""
    llm = _FakeLLM([
        '{"policy_number":"6130104121920260000000182"}',   # 首页读对
        '{"policy_number":"61301041219202600000000182"}',  # 第 2 页多插一个 0
    ])
    ex = OCRExtractor(llm_client=llm)
    meta = ex.extract_overall_metadata(page_images=["a", "b"], max_pages=2)
    # 1:1 平票 → 不覆盖首页结果，但必须标记冲突供人工核对
    assert meta["policy_number_conflict"] is True
    assert meta["policy_number"] == "6130104121920260000000182"


def test_extract_overall_metadata_majority_overrides_first_page():
    """3 页中 2 页一致 → 多数票覆盖首页的误读"""
    llm = _FakeLLM([
        '{"policy_number":"61301041219202600000000182"}',  # 首页误读（多一个 0）
        '{"policy_number":"6130104121920260000000182"}',
        '{"policy_number":"6130104121920260000000182"}',
    ])
    ex = OCRExtractor(llm_client=llm)
    meta = ex.extract_overall_metadata(page_images=["a", "b", "c"], max_pages=3)
    assert meta["policy_number"] == "6130104121920260000000182"
    assert meta["policy_number_conflict"] is True


def test_extract_overall_metadata_without_images_returns_empty():
    ex = OCRExtractor(llm_client=_FakeLLM([]))
    assert ex.extract_overall_metadata(page_images=[]) == {}


def test_extract_overall_metadata_requires_llm():
    ex = OCRExtractor(llm_client=None)
    with pytest.raises(ValueError):
        ex.extract_overall_metadata(page_images=["ZmFrZQ=="])


# ------------------------------------------------------------------ 6. PersonnelExtractorNode 集成

class _FakeOCRExtractor:
    """模拟扫描件 OCR 提取器：人员无日期，但版面元数据带保险期间"""

    def __init__(self, meta):
        self._meta = meta
        self.meta_calls = 0

    def extract_overall_metadata(self, page_images=None, max_pages=1):
        self.meta_calls += 1
        return dict(self._meta)

    def extract(self, text="", policy_holder="", insurance_company="", page_images=None):
        return [
            InsuredPerson(
                name="陈强",
                id_number="370303198007313110",
                id_type="身份证",
                company="山东诚晟陶瓷科技有限公司",
                job_title="陶瓷原料准备工",
                occupation_class="3",
                modification_type="增保",
            )
        ]


def _scanned_state():
    return {
        "pdf_document": {
            "file_path": "x.pdf",
            "file_name": "10月1-5类80万含猝死·原始保单.pdf",
            "total_pages": 1,
            "pages": [
                {
                    "page_number": 1,
                    "text": "",
                    "image_base64": "",
                    "has_meaningful_text": False,
                    "text_length": 0,
                }
            ],
            "is_scanned": True,
            "insurance_company": "",
        },
        "format_hint": "ocr",
        "list_pages": [],
        "policy_holder": "",
        "insurance_company": "",
        "page_images": ["ZmFrZQ=="],
        "working_memory": {},
        "tool_results": {},
    }


def test_scanned_person_gets_dates_from_ocr_metadata():
    """核心回归：扫描件人员的日期由版面元数据兜底填充"""
    meta = {
        "policy_number": "6130104121920260000000182",
        "overall_start_date": "2026-10-01",
        "overall_end_date": "2026-10-31",
        "insurance_company": "黄河财产保险股份有限公司",
        "total_persons": "11950",
    }
    fake = _FakeOCRExtractor(meta)
    node = PersonnelExtractorNode(ocr_extractor=fake)
    out = node(_scanned_state())

    persons = out["extraction_result"]["insured_persons"]
    assert len(persons) == 1
    assert persons[0]["start_date"] == "2026-10-01"
    assert persons[0]["end_date"] == "2026-10-31"

    # 保单号与整体期间要回写到结果与 working_memory，供下游关联主保单/入库
    assert out["extraction_result"]["policy_number"] == "6130104121920260000000182"
    assert out["extraction_result"]["overall_start_date"] == "2026-10-01"
    assert out["extraction_result"]["overall_end_date"] == "2026-10-31"
    assert out["working_memory"]["policy_number"] == "6130104121920260000000182"
    assert fake.meta_calls == 1


def test_scanned_existing_working_memory_wins_over_ocr_metadata():
    """已有值（文字层）优先，不被 OCR 元数据覆盖"""
    meta = {
        "policy_number": "999999999999999999999999",
        "overall_start_date": "2020-01-01",
        "overall_end_date": "2020-12-31",
    }
    fake = _FakeOCRExtractor(meta)
    node = PersonnelExtractorNode(ocr_extractor=fake)
    state = _scanned_state()
    state["working_memory"] = {
        "policy_number": "662290212192026BZN00000765",
        "overall_start_date": "2026-05-14",
        "overall_end_date": "2026-11-13",
    }
    out = node(state)

    assert out["extraction_result"]["policy_number"] == "662290212192026BZN00000765"
    persons = out["extraction_result"]["insured_persons"]
    assert persons[0]["start_date"] == "2026-05-14"
    assert persons[0]["end_date"] == "2026-11-13"


def test_ocr_metadata_failure_does_not_block_person_extraction():
    """版面元数据 OCR 失败时，人员仍要照常提取（降级为无元数据）"""

    class _BrokenOCRExtractor(_FakeOCRExtractor):
        def extract_overall_metadata(self, page_images=None, max_pages=1):
            raise RuntimeError("LLM 调用失败")

    node = PersonnelExtractorNode(ocr_extractor=_BrokenOCRExtractor({}))
    out = node(_scanned_state())

    persons = out["extraction_result"]["insured_persons"]
    assert len(persons) == 1
    assert persons[0]["start_date"] in (None, "")
    assert persons[0]["end_date"] in (None, "")


def test_text_layer_path_does_not_call_ocr_metadata():
    """文字层 PDF（format_hint=table）不触发版面元数据 OCR —— 既有行为零变化"""

    class _ShouldNotBeCalled(_FakeOCRExtractor):
        def extract_overall_metadata(self, page_images=None, max_pages=1):
            raise AssertionError("文字层路径不应调用版面元数据 OCR")

    node = PersonnelExtractorNode(ocr_extractor=_ShouldNotBeCalled({}))
    state = _scanned_state()
    state["format_hint"] = "table"
    state["list_pages"] = [1]
    state["pdf_document"]["pages"][0]["text"] = "序号 姓名 证件号\n1 陈强 370303198007313110\n"
    state["pdf_document"]["pages"][0]["has_meaningful_text"] = True
    out = node(state)
    assert out["extraction_result"]["format_used"] == "table"


# ------------------------------------------------------------------ 7. 零歧义消解

def test_is_zero_ambiguity_detects_extra_zero():
    a = "6130104121920260000000182"   # 25 位（正确）
    b = "61301041219202600000000182"  # 26 位（多一个 0）
    assert OCRExtractor._is_zero_ambiguity(a, b) is True
    assert OCRExtractor._is_zero_ambiguity(b, a) is True


def test_is_zero_ambiguity_rejects_different_numbers():
    assert OCRExtractor._is_zero_ambiguity(
        "6130104121920260000000182", "662290212192026BZN00000765"
    ) is False
    assert OCRExtractor._is_zero_ambiguity("123", "123") is False


def test_tie_with_zero_ambiguity_is_not_auto_resolved():
    """1:1 平票且仅差 0 的个数 → **不自动消解**，保留首页读数并标记冲突

    实测证据：视觉模型读长数字串时，「多插 0」与「漏 0」都会发生
    （25 位的真值既被读成 26 位也被读成 24 位），单靠位数无法判定谁对。
    因此不做启发式覆盖，改为标记冲突交人工核对，避免静默污染保单号。
    """
    llm = _FakeLLM([
        '{"policy_number":"613010412192026000000000182"}',  # 首页：多两个 0
        '{"policy_number":"6130104121920260000000182"}',   # 第 2 页：正确
    ])
    ex = OCRExtractor(llm_client=llm)
    meta = ex.extract_overall_metadata(page_images=["a", "b"], max_pages=2)
    # 保留首页读数，不做位数启发式覆盖
    assert meta["policy_number"] == "613010412192026000000000182"
    assert meta["policy_number_conflict"] is True
    assert len(meta["policy_number_votes"]) == 2


def test_majority_vote_overrides_first_page_misread():
    """多页中多数票一致 → 覆盖首页误读（多数票是可靠信号）"""
    llm = _FakeLLM([
        '{"policy_number":"61301041219202600000000182"}',  # 首页误读
        '{"policy_number":"6130104121920260000000182"}',
        '{"policy_number":"6130104121920260000000182"}',
        '{"policy_number":"6130104121920260000000182"}',
    ])
    ex = OCRExtractor(llm_client=llm)
    meta = ex.extract_overall_metadata(page_images=["a", "b", "c", "d"], max_pages=4)
    assert meta["policy_number"] == "6130104121920260000000182"
    assert meta["policy_number_conflict"] is True
