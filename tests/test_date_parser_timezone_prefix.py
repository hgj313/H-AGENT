# -*- coding: utf-8 -*-
"""date_parser 整体期间解析回归测试

覆盖场景：
1. 申能财产保险格式 — "自北京时间2026年...起至...止"（2026-09-28 新增修复）
2. 历史格式不得回归 — 利宝 / 平安养老 / 北部湾 / 中国人寿 block_kv / 斜杠

回归背景：2026-09-28 修复前，_OVERALL_PATTERNS 全部要求"自"后紧跟数字，
遇到"自北京时间2026年..."整体期间解析返回 (None, None)，
导致吴祖华保单 9 人 start_date/end_date 全部为 NULL。
教训（同 9-28 inline _ID_REGEX）：扩展正则必须覆盖旧格式回归测试。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from insurance_agent.tools.date_parser import extract_overall_insurance_period  # noqa: E402


CASES = [
    # (用例名, 输入文本, 期望 (start, end))
    (
        "申能财险_自北京时间起至（本次修复目标）",
        "保险期间：自北京时间2026年03月06日0时起至2027年03月05日24时止，共计365天。",
        ("2026-03-06", "2027-03-05"),
    ),
    (
        "申能财险_带空格日期+北京时间",
        "保险期间：自 北京时间 2026 年 03 月 06 日 0 时起至 2027 年 03 月 05 日 24 时止",
        ("2026-03-06", "2027-03-05"),
    ),
    # ---- 历史格式回归 ----
    (
        "利宝_标准中文起至",
        "保险期间：自2026年06月17日0时起至2026年09月16日24时止",
        ("2026-06-17", "2026-09-16"),
    ),
    (
        "利宝_秒级中文时间",
        "自2026年06月24日 00时00分00秒起至2026年09月24日 00时00分00秒止",
        ("2026-06-24", "2026-09-24"),
    ),
    (
        "平安养老_保险起期止期独立字段",
        "保险起期（北京时间）：2026 年06 月20 日00 时 保险止期（北京时间）：2027 年06 月19 日24 时",
        ("2026-06-20", "2027-06-19"),
    ),
    (
        "平安养老_标签后无括号变体",
        "保险起期：北京时间2026年06月20日00时 保险止期：北京时间2027年06月19日24时",
        ("2026-06-20", "2027-06-19"),
    ),
    (
        "北部湾_日期数字间空格",
        "保险期间：自 2026 年 10 月 01 日 零时起至 2027 年 10 月 01 日 24 时止",
        ("2026-10-01", "2027-10-01"),
    ),
    (
        "中国人寿_block_kv双字段",
        "保险合同满期日期：2027年06月28日  保险合同生效日期：2026年06月29日 零时零分零秒",
        ("2026-06-29", "2027-06-28"),
    ),
    (
        "通用_斜杠分隔",
        "自2026/06/24 00:00:00起至2026/09/24 00:00:00止",
        ("2026-06-24", "2026-09-24"),
    ),
    (
        "通用_年月日横杠分隔",
        "自2026-06-24 00:00:00起至2026-09-24 00:00:00止",
        ("2026-06-24", "2026-09-24"),
    ),
]


def test_overall_period_all_formats():
    failures = []
    for name, text, expected in CASES:
        got = extract_overall_insurance_period(text)
        if got != expected:
            failures.append(f"{name}: 期望 {expected}, 实际 {got}")
    assert not failures, "整体期间解析回归:\n" + "\n".join(failures)


def test_timezone_prefix_optional():
    """_TIMEZONE_PREFIX 必须是可选的，不能强制要求时区词"""
    assert extract_overall_insurance_period("自2026年06月17日0时起至2026年09月16日24时止") == (
        "2026-06-17",
        "2026-09-16",
    )


def test_empty_input_returns_none():
    assert extract_overall_insurance_period("") == (None, None)
    assert extract_overall_insurance_period("无保单号的说明文档") == (None, None)


def test_company_prefix_shenyong():
    """申能财产保险号段兜底（2026-09-28 新增）"""
    from insurance_agent.tools.company_extractor import detect_insurance_company_by_policy_number

    assert detect_insurance_company_by_policy_number("6513630150160260000001") == "申能财产保险"
    # 历史号段不得回归
    assert detect_insurance_company_by_policy_number("PZFZ26440137230000000075") == "中国大地财产保险"
    assert detect_insurance_company_by_policy_number("PEAC20261201XXXX") == "平安养老保险"
    assert detect_insurance_company_by_policy_number("ASHH123456") == "中国太平洋财产保险"
    assert detect_insurance_company_by_policy_number("8041472013XXXX") == "北部湾财产保险"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))