"""
阳光保险《变更被保人》批单格式适配回归测试
==========================================

来源：减少陈洪、增加周润.pdf（阳光保险 HGC 批单 015）
- 批单号：HGC182700YQH0M00Y400_015
- 保单号：HGC182700YQH0M00Y400
- 批改类型：《变更被保人》
- 内容：被保险人姓名由陈洪变更为周润,证件号码由510218198207242535变更为500381200601135218

测试要点：
1. _extract_change 正确解析"由X变更为Y"格式
2. _extract_change 标记 old=减保, new=增保
3. _INLINE_MARKERS 包含"变更为"（路由判定）
4. personnel_extractor_node 处理 inline marker 但 list_pages 为空的情况
5. 不破坏已有的 阳光 inline（被保险人姓名:）/ 利宝 inline（雇员姓名:）/ 太保 替换
"""

import sys
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def test_extract_change_basic():
    """测试 _extract_change 基本功能"""
    from insurance_agent.extractors.inline_extractor import InlineExtractor

    # 标准格式：姓名由X变更为Y,证件号码由A变更为B
    text = """《变更被保人》
被保险人姓名由陈洪变更为周润,证件号码由510218198207242535变更为500381200601135218,
"""

    extractor = InlineExtractor()
    persons = extractor._extract_change(text, policy_holder="重庆域豹")

    assert len(persons) == 2, f"期望 2 人，实际 {len(persons)}"

    # 减保：陈洪
    chen_hong = next(p for p in persons if p.name == "陈洪")
    assert chen_hong.id_number == "510218198207242535"
    assert chen_hong.modification_type == "减保"
    assert chen_hong.company == "重庆域豹"

    # 增保：周润
    zhou_run = next(p for p in persons if p.name == "周润")
    assert zhou_run.id_number == "500381200601135218"
    assert zhou_run.modification_type == "增保"
    assert zhou_run.company == "重庆域豹"

    print("✅ test_extract_change_basic")


def test_extract_change_multiple_groups():
    """测试多个变更组"""
    from insurance_agent.extractors.inline_extractor import InlineExtractor

    # 多组变更
    text = """《变更被保人》
被保险人姓名由陈洪变更为周润,证件号码由510218198207242535变更为500381200601135218,
《变更被保人》
被保险人姓名由李四变更为王五,证件号码由123456789012345678变更为987654321098765432,
"""

    extractor = InlineExtractor()
    persons = extractor._extract_change(text, policy_holder="测试公司")

    assert len(persons) == 4, f"期望 4 人，实际 {len(persons)}"

    # 按中文 Unicode 排序（与 sorted() 一致）
    names = sorted([p.name for p in persons])
    assert set(names) == {"王五", "陈洪", "李四", "周润"}, f"姓名错误: {names}"

    # 验证 modification_type
    types = {p.name: p.modification_type for p in persons}
    assert types["陈洪"] == "减保"
    assert types["周润"] == "增保"
    assert types["李四"] == "减保"
    assert types["王五"] == "增保"

    print("✅ test_extract_change_multiple_groups")


def test_inline_markers_includes_biangengwei():
    """测试 _INLINE_MARKERS 包含 '变更为'"""
    from insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node import (
        _INLINE_MARKERS,
    )

    assert "变更为" in _INLINE_MARKERS, f"_INLINE_MARKERS 缺 '变更为': {_INLINE_MARKERS}"

    print("✅ test_inline_markers_includes_biangengwei")


def test_extract_routes_to_change():
    """测试 extract() 路由到 _extract_change"""
    from insurance_agent.extractors.inline_extractor import InlineExtractor

    text = """《变更被保人》
被保险人姓名由陈洪变更为周润,证件号码由510218198207242535变更为500381200601135218,
"""

    extractor = InlineExtractor()
    persons = extractor.extract(text, policy_holder="测试公司")

    assert len(persons) == 2
    # 验证是 _extract_change 的结果（不是 _extract_from_segment）
    names = [p.name for p in persons]
    assert "由陈洪变" not in names, f"路由失败，仍走 _extract_from_segment: {names}"
    assert "陈洪" in names
    assert "周润" in names

    # 验证 modification_type
    types = {p.name: p.modification_type for p in persons}
    assert types["陈洪"] == "减保", f"陈洪 modification_type 错误: {types}"
    assert types["周润"] == "增保", f"周润 modification_type 错误: {types}"

    print("✅ test_extract_routes_to_change")


def test_existing_inline_formats_not_broken():
    """回归：已有 inline 格式不能被破坏"""

    # 阳光 inline（被保险人姓名:）
    from insurance_agent.extractors.inline_extractor import InlineExtractor
    extractor = InlineExtractor()

    text1 = "被保险人姓名:杨仕亮,证件号码:522224196607232434"
    persons1 = extractor.extract(text1, policy_holder="测试")
    assert len(persons1) == 1
    assert persons1[0].name == "杨仕亮"
    assert persons1[0].id_number == "522224196607232434"
    assert persons1[0].modification_type == "增保"

    # 利宝 inline（雇员姓名：）
    text2 = "雇员姓名：张三，证件号：510223196903036833，工种描述：砌筑工"
    persons2 = extractor.extract(text2, policy_holder="测试")
    assert len(persons2) == 1
    assert persons2[0].name == "张三"
    assert persons2[0].id_number == "510223196903036833"

    # 太保 替换（替换为人员）
    text3 = "由人员 邓礼山 证件号码 512223197004182972 替换为人员 李红 证件号码 500231198711087553"
    persons3 = extractor.extract(text3, policy_holder="测试")
    assert len(persons3) == 2
    names3 = {p.name: p.modification_type for p in persons3}
    assert names3["邓礼山"] == "减保"
    assert names3["李红"] == "增保"

    print("✅ test_existing_inline_formats_not_broken")


def test_change_format_real_pdf_end_to_end():
    """端到端：真实 PDF 提取验证"""
    import requests

    pdf_path = Path(r"D:\Users\Administrator\Downloads\减少陈洪、增加周润.pdf")
    if not pdf_path.exists():
        pdf_path = Path(r"C:\Users\Administrator\Downloads\减少陈洪、增加周润.pdf")
    if not pdf_path.exists():
        print(f"⚠️ test_change_format_real_pdf_end_to_end: PDF 不存在 ({pdf_path})，跳过端到端测试")
        return

    try:
        resp = requests.post(
            "http://localhost:8765/api/upload",
            files={"file": open(str(pdf_path), "rb")},
            timeout=60,
        )
        data = resp.json()

        assert data.get("success") is True, f"提取失败: {data}"
        assert data.get("total_persons") == 2, f"期望 2 人，实际 {data.get('total_persons')}"
        assert data.get("total_add") == 1
        assert data.get("total_remove") == 1

        result = data["results"][0]
        assert result["insurance_company"] == "阳光保险"
        assert result["policy_number"] == "HGC182700YQH0M00Y400_015"
        assert result["overall_start_date"] == "2026-07-17"

        persons = result["persons"]
        chen_hong = next(p for p in persons if p["name"] == "陈洪")
        assert chen_hong["id_number"] == "510218198207242535"
        assert chen_hong["modification_type"] == "减保"

        zhou_run = next(p for p in persons if p["name"] == "周润")
        assert zhou_run["id_number"] == "500381200601135218"
        assert zhou_run["modification_type"] == "增保"

        print(f"✅ test_change_format_real_pdf_end_to_end")
    except requests.exceptions.ConnectionError:
        print("⚠️ test_change_format_real_pdf_end_to_end: 服务未启动，跳过端到端测试")
    except Exception as e:
        raise


def main():
    """运行所有测试"""
    print("=" * 70)
    print("阳光保险《变更被保人》批单格式适配回归测试")
    print("=" * 70)

    tests = [
        test_extract_change_basic,
        test_extract_change_multiple_groups,
        test_inline_markers_includes_biangengwei,
        test_extract_routes_to_change,
        test_existing_inline_formats_not_broken,
        test_change_format_real_pdf_end_to_end,
    ]

    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")

    print()
    print("=" * 70)
    print(f"通过: {passed}/{len(tests)}")
    print("=" * 70)
    return passed == len(tests)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)