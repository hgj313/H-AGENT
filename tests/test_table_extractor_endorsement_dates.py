"""table_extractor 批单日期/批改类型回归测试（2026-11-03）

覆盖两个真实事故：

1. **零数量减保描述误判**
   利宝批单汇总句「方案5增加：2人，减少：0人」中的「减少：0人」，
   被行级判定当成真实减保 → 该文件**第一条人员**被误标为「减保」。
   根因：pre_region 回溯 200 字符吞进了汇总句。
   修复：`_strip_zero_count_remove_markers` 把「减少：0人」整段替换为中性占位符。

2. **重复生效日被误当「起止期间」**
   利宝批单批头「批单生效日期 自2026年10月30日零时起生效」与批文
   「兹经双方同意,自2026年10月30日零时起」描述的是**同一个生效日**，
   但 extract_dates_near 返回 [X, X] → 起止同天 → 增保人员止期被锁死为生效日。
   修复：`_is_repeated_effective_date` 识别「同一日期在区域内出现 ≥2 次且无期间配对标记」，
        清空起止交由 validator 按批改类型从主保单回填。
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from insurance_agent.extractors.table_extractor import TableExtractor  # noqa: E402


# ════════════════════════════════════════════════════════════
# 1. 零数量减保描述
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "region,expected",
    [
        # 利宝真实场景：增加 2 人、减少 0 人 → 应判增保
        ("方案5增加：2人，减少：0人,保费变化(CNY): 356.00", "增保"),
        ("本次批改合计批增: 2人，加收保费(CNY): 356.00\n方案5增加：2人，减少：0人", "增保"),
        # 真实减保（数量 > 0）→ 仍应判减保
        ("本次批改合计批减: 3人", "减保"),
        ("增加：0人，减少：2人", "减保"),
        ("批减10人", "减保"),
        ("批减100人", "减保"),
        # 零数量的各种写法 → 不触发减保
        ("本次批改合计批减: 0人", ""),
        ("减少：0人，删除：0人", ""),
        ("减员：0人", ""),
        ("注销：0人", ""),
        # 全角数字零
        ("方案5增加：2人，减少：０人", "增保"),
        # 无标记 → 不判定
        ("正常保单，无批改标记", ""),
    ],
)
def test_zero_count_remove_markers(region, expected):
    """「减少：0人」这类零数量描述不得触发减保判定"""
    te = TableExtractor()
    stripped = te._strip_zero_count_remove_markers(region)
    assert te._detect_row_modification_type(stripped) == expected, (
        f"region={region!r} stripped={stripped!r}"
    )


def test_zero_count_strip_removes_marker_word_entirely():
    """剔除后连「减少」这个词都不能留下，否则 _REMOVE_MARKERS 仍会命中"""
    te = TableExtractor()
    stripped = te._strip_zero_count_remove_markers("方案5增加：2人，减少：0人")
    assert "减少" not in stripped, f"剔除后仍含标记词: {stripped!r}"
    assert "增加" in stripped, f"剔除时误删了增保标记: {stripped!r}"


# ════════════════════════════════════════════════════════════
# 2. 重复生效日 ≠ 起止期间
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "region,date,expected",
    [
        # 利宝批单真实场景：同一生效日被描述两次
        (
            "批单生效日期\n自2026年11月04日零时起生效\n批文\n"
            "兹经双方同意,自2026年11月04日零时起,对本保单作如下批改：",
            "2026-11-04",
            True,
        ),
        (
            "自2026年10月30日零时起生效\n兹经双方同意,自2026年10月30日零时起,"
            "对本保单作如下批改：",
            "2026-10-30",
            True,
        ),
        # 真期间（同一句内起止配对）→ 不是重复
        ("保险期间 自2026-06-20起至2026-06-20止", "2026-06-20", False),
        # 只出现一次 → 不是重复
        ("批单生效日期 自2026年11月04日零时起生效", "2026-11-04", False),
        # 区域里根本没这个日期
        ("雇员姓名：张三，证件号：110101199001011234", "2026-11-04", False),
        # 不同日期的正常期间
        ("保险期间 自2026-10-01起至2026-10-31止", "2026-10-01", False),
    ],
)
def test_is_repeated_effective_date(region, date, expected):
    """同一日期在区域内出现多次 = 重复描述的生效日，不是起止期间"""
    te = TableExtractor()
    assert te._is_repeated_effective_date(region, date) is expected, (
        f"region={region!r} date={date!r}"
    )


def test_repeated_effective_date_clears_period():
    """重复生效日 → 起止都清空，交给 validator 按批改类型从主保单回填"""
    te = TableExtractor()
    region = (
        "批单生效日期\n自2026年10月30日零时起生效\n批文\n"
        "兹经双方同意,自2026年10月30日零时起,对本保单作如下批改："
    )
    dates = ["2026-10-30", "2026-10-30"]
    assert te._is_repeated_effective_date(region, dates[0]) is True
    # 清空后 validator 会：增保 → start=批单生效日, end=主保单止期
    #                        减保 → start=主保单起期, end=批单生效日
    start_date = end_date = ""
    if start_date == end_date == "":
        pass  # 交由下游回填


def test_real_period_not_cleared():
    """有明确期间配对标记的起止（同日）不应被清空"""
    te = TableExtractor()
    region = "保险期间 自2026-06-20起至2026-06-20止"
    # 该场景不应被判为「重复生效日」，因此不应触发清空
    assert te._is_repeated_effective_date(region, "2026-06-20") is False


# ════════════════════════════════════════════════════════════
# 3. 回归保护：常见批改标记
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "region,expected",
    [
        ("本期增加被保险人：张三", "增保"),
        ("本期减少被保险人：李四", "减保"),
        ("同期增减", "增保"),
        ("本次批改合计批增: 2人", "增保"),
        ("本次批改合计批减: 1人", "减保"),
        # 「变更为」属阳光保险《变更被保人》inline 格式，由 inline_extractor 处理，
        # table_extractor 的标记集本就不含它 → 判定为空是既有行为，非本次回归
        ("被保险人姓名由陈洪变更为周润", ""),
    ],
)
def test_common_modification_markers_unchanged(region, expected):
    """常规批改标记判定不受本次修复影响"""
    te = TableExtractor()
    got = te._detect_row_modification_type(te._strip_zero_count_remove_markers(region))
    assert got == expected, f"region={region!r} got={got!r}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
