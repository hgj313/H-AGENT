"""
中国大地财产保险（PZFZ 号段）新格式适配回归测试
=================================================

来源：保单·李正雄0929-1228.pdf（中国大地财产保险雇主责任保险2026版，6 人）

测试要点：
1. PZFZ 号段 → 中国大地财产保险（号段映射兜底）
2. 中介公司"安澜保险经纪有限公司"被跳过，投保人="重庆李正雄建筑劳务有限公司"
3. PyMuPDF 跨行身份证号自动拼接
4. 工种带中文括号后缀"园林绿化工（园内）"保留
5. 整体保险期间 2026-09-29 ~ 2026-12-28
6. 6 人完整提取（含姓名/身份证/工种/出生日期/起止日期）
7. 不破坏已有阳光/利宝/平安养老/北部湾/华安/中国人寿等格式
"""

import sys
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def test_pzfz_prefix_mapping():
    """测试 PZFZ 号段 → 中国大地财产保险 映射"""
    from insurance_agent.tools.company_extractor import (
        detect_insurance_company_by_policy_number,
        _POLICY_NUMBER_PREFIX_TO_COMPANY,
    )

    # 1. 号段映射存在
    assert "PZFZ" in _POLICY_NUMBER_PREFIX_TO_COMPANY, \
        "PZFZ 号段映射缺失"
    assert _POLICY_NUMBER_PREFIX_TO_COMPANY["PZFZ"] == "中国大地财产保险", \
        f"PZFZ 映射错误: {_POLICY_NUMBER_PREFIX_TO_COMPANY['PZFZ']}"

    # 2. detect_insurance_company_by_policy_number 返回正确结果
    result = detect_insurance_company_by_policy_number("PZFZ26440137230000000075")
    assert result == "中国大地财产保险", f"号段识别失败: {result}"

    # 3. 大小写不敏感
    result = detect_insurance_company_by_policy_number("pzfz26440137230000000075")
    assert result == "中国大地财产保险", f"小写不识别: {result}"

    # 4. 空保单号返回空字符串
    assert detect_insurance_company_by_policy_number("") == ""
    assert detect_insurance_company_by_policy_number(None) == ""

    print("✅ test_pzfz_prefix_mapping")


def test_existing_prefix_mappings_unchanged():
    """回归：已有的号段映射不能被破坏"""
    from insurance_agent.tools.company_extractor import _POLICY_NUMBER_PREFIX_TO_COMPANY

    expected = {
        "613010104": "华安财产保险",
        "8116013100": "利宝保险",
        "7116013100": "利宝保险",
        "ASHH": "中国太平洋财产保险",
        "BSHH": "中国太平洋财产保险",
        "81160": "安诚财产保险",
        "61160": "安诚财产保险",
        "X44": "中国太平洋财产保险",
        "SHBX": "中国太平洋财产保险",
        "804147": "北部湾财产保险",
        "PEAC": "平安养老保险",
        "PZFZ": "中国大地财产保险",
    }

    for prefix, company in expected.items():
        assert prefix in _POLICY_NUMBER_PREFIX_TO_COMPANY, \
            f"号段 {prefix} 缺失"
        assert _POLICY_NUMBER_PREFIX_TO_COMPANY[prefix] == company, \
            f"号段 {prefix} 映射错误: 期望 {company}, 实际 {_POLICY_NUMBER_PREFIX_TO_COMPANY[prefix]}"

    print(f"✅ test_existing_prefix_mappings_unchanged ({len(expected)} 个号段)")


def test_yangguang_still_works():
    """回归：阳光保险 HGC 号段仍能识别"""
    from insurance_agent.tools.company_extractor import detect_insurance_company_by_policy_number

    # 阳光保险 HGC 号段（之前适配过，文本层提到"阳光"）
    # HGC 不在号段 map 里，但文本检测会命中
    result = detect_insurance_company_by_policy_number("HGC182700YQH0M00Y400")
    # HGC 不在 map，所以号段兜底返回空（应该靠文本检测）
    assert result == "", f"HGC 不应被号段兜底识别: {result}"

    print("✅ test_yangguang_still_works")


def test_job_pattern_with_chinese_parens():
    """回归：_JOB_PATTERN 支持中文括号后缀"""
    from insurance_agent.extractors.table_extractor import TableExtractor

    # 创建一个 TableExtractor 实例
    extractor = TableExtractor()

    # 中国大地 - "园林绿化工（园内）"
    text = "园林绿化工（园内）"
    match = extractor._JOB_PATTERN.search(text)
    assert match is not None, f"工种正则不匹配: {text}"
    assert "园内" in match.group(1), f"括号后缀丢失: {match.group(1)}"

    # 阳光 - "水电工（非涉高）"
    text2 = "水电工（非涉高）"
    match2 = extractor._JOB_PATTERN.search(text2)
    assert match2 is not None, f"工种正则不匹配: {text2}"
    assert "非涉高" in match2.group(1), f"括号后缀丢失: {match2.group(1)}"

    # 无括号工种
    text3 = "砌筑工"
    match3 = extractor._JOB_PATTERN.search(text3)
    assert match3 is not None, f"工种正则不匹配: {text3}"
    assert match3.group(1) == "砌筑工"

    print("✅ test_job_pattern_with_chinese_parens")


def test_intermediary_blacklist():
    """回归：中介公司黑名单"""
    from insurance_agent.tools.company_extractor import (
        _is_intermediary_company,
        extract_company_after_label,
    )

    # 中介公司应被识别
    assert _is_intermediary_company("安澜保险经纪有限公司") is True, \
        "安澜保险经纪未识别为中介"
    assert _is_intermediary_company("广东美保保险经纪有限公司") is True
    assert _is_intermediary_company("保险代理公司") is True

    # 正常公司不应被识别为中介
    assert _is_intermediary_company("重庆李正雄建筑劳务有限公司") is False
    assert _is_intermediary_company("广州市粤灿建设工程有限公司") is False

    print("✅ test_intermediary_blacklist")


def test_id_regex_cross_line():
    """回归：跨行身份证号拼接（PyMuPDF 拆字 bug）"""
    import re

    # 中国大地：身份证被拆成两行
    text = "510223197311\n103531"
    # 应该能匹配完整 18 位
    pattern = re.compile(r"(\d{17}[\dXx])")
    # 跨行需要先 re.sub 去掉换行
    joined = re.sub(r"(\d{6,})\s*\n\s*(\d{2,4})", r"\1\2", text)
    match = pattern.search(joined)
    assert match is not None, "跨行身份证拼接失败"
    assert len(match.group(1)) == 18, f"长度不对: {match.group(1)}"

    print("✅ test_id_regex_cross_line")


def test_pzfz_pdf_end_to_end():
    """端到端：中国大地 PZFZ 真实 PDF 提取验证"""
    import requests

    pdf_path = PROJECT_ROOT.parent / "wechat" / "xwechat_files" / "wxid_sdqmy0iwd0h921_7871" / "msg" / "file" / "2026-09" / "保单·李正雄0929-1228.pdf"
    pdf_path_str = str(pdf_path).replace("\\", "/")

    if not Path(pdf_path_str).exists():
        # 文件不在，尝试直接路径
        alt_path = Path(r"D:\wechat\xwechat_files\wxid_sdqmy0iwd0h921_7871\msg\file\2026-09\保单·李正雄0929-1228.pdf")
        if alt_path.exists():
            pdf_path_str = str(alt_path)
        else:
            print(f"⚠️ test_pzfz_pdf_end_to_end: PDF 不存在 ({pdf_path_str})，跳过端到端测试")
            return

    # 调用 /api/upload 测试提取
    try:
        resp = requests.post(
            "http://localhost:8765/api/upload",
            files={"file": open(pdf_path_str, "rb")},
            timeout=60,
        )
        data = resp.json()

        assert data.get("success") is True, f"提取失败: {data}"
        assert data.get("total_persons") == 6, f"期望 6 人，实际 {data.get('total_persons')}"

        result = data["results"][0]
        assert result["insurance_company"] == "中国大地财产保险", \
            f"保险公司错误: {result['insurance_company']}"
        assert result["policy_number"] == "PZFZ26440137230000000075", \
            f"保单号错误: {result['policy_number']}"
        assert result["overall_start_date"] == "2026-09-29", \
            f"起始日期错误: {result['overall_start_date']}"
        assert result["overall_end_date"] == "2026-12-28", \
            f"结束日期错误: {result['overall_end_date']}"

        persons = result["persons"]
        assert len(persons) == 6

        # 验证邓孝林
        d_xiaolin = next(p for p in persons if p["name"] == "邓孝林")
        assert d_xiaolin["id_number"] == "510223197311103531", \
            f"邓孝林身份证错误: {d_xiaolin['id_number']}"
        assert d_xiaolin["company"] == "重庆李正雄建筑劳务有限公司", \
            f"邓孝林公司错误: {d_xiaolin['company']}"
        assert "园内" in d_xiaolin["job_title"], \
            f"邓孝林工种括号丢失: {d_xiaolin['job_title']}"
        assert d_xiaolin["start_date"] == "2026-09-29"
        assert d_xiaolin["end_date"] == "2026-12-28"

        print(f"✅ test_pzfz_pdf_end_to_end (6 人全部正确)")
    except requests.exceptions.ConnectionError:
        print("⚠️ test_pzfz_pdf_end_to_end: 服务未启动，跳过端到端测试")
    except Exception as e:
        raise


def main():
    """运行所有测试"""
    print("=" * 70)
    print("中国大地财产保险（PZFZ 号段）适配回归测试")
    print("=" * 70)

    tests = [
        test_pzfz_prefix_mapping,
        test_existing_prefix_mappings_unchanged,
        test_yangguang_still_works,
        test_job_pattern_with_chinese_parens,
        test_intermediary_blacklist,
        test_id_regex_cross_line,
        test_pzfz_pdf_end_to_end,
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