"""平安产险『电子保单_雇主安心保-四川』新格式适配回归测试

PDF: 电子保单_成都林盛鑫屹园林绿化工程有限公司_小微_12652416800201450969_lnl.pdf

格式特征（2026-10-08 新增）：
1. 17 页 PDF，4-5 页"投保雇员清单"
2. 表格列：序号 / 姓名 / 证件号码 / 职业类别 / 岗位名称
3. **身份证脱敏 14+4 新格式**：`51102519741110****`（6 地区码 + 4 年 + 2 月 + 2 日 + 4 星）
   不同于之前的 6+8+4 格式（`412702********2432`，平安养老 PEAC）
4. **职业类别 + 岗位名称 双列**：职业类别列存"三类职业"，岗位名称列存"绿化栽植工"
5. 保单号 20 位数字（`12652416800201450969`），保险公司识别为"中国平安"

修复点：
1. id_validator.py 新增 _MASKED_ID_PATTERN_TAIL = (\d{14})\*{4} 支持 14+4 脱敏
2. metadata_extractor_node.py _is_list_continuation_page 正则扩展支持 14+4 续页识别
3. inline_extractor.py _ID_REGEX 扩展支持 14+4
4. table_extractor.py job_title 提取逻辑改造：
   - _OCCUPATION_CLASS_PATTERN 命中值 → occupation_class 字段（不再吞掉 job_title）
   - 继续找 _JOB_PATTERN 匹配作为 job_title（取"绿化栽植工"）
   - job_title 仍为空时退化到 occupation_class（兼容 PEAC 无岗位名称列的格式）
5. table_extractor.py 跨行工种合并规则（4b）增加占位符保护：
   - "三类\n职业" → "三类职业\uE000"（\uE000 = 私有区字符，绝不出现在 PDF 文本里）
   - 防止"三类职业\n绿化栽植工"被 4b 错误合并成"三类职业绿化栽植工"
   - 合并后还原占位符
"""

import re
import sys
from pathlib import Path

# 把项目根加到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

failed = 0
passed = 0


def check(name, condition, detail=""):
    global failed, passed
    if condition:
        print(f"✅ {name}")
        passed += 1
    else:
        print(f"❌ {name} - {detail}")
        failed += 1


def test_masked_id_pattern_14_4():
    """单元测试：14+4 脱敏 ID 正则"""
    from insurance_agent.tools.id_validator import (
        is_valid_chinese_id, extract_chinese_id_from_text,
    )

    # is_valid_chinese_id
    check("14+4 (Pingan) 51102519741110****",
          is_valid_chinese_id("51102519741110****"))
    check("14+4 (Beijing) 11010119491001****",
          is_valid_chinese_id("11010119491001****"))
    check("14+4 (alt) 32010519850101****",
          is_valid_chinese_id("32010519850101****"))

    # 6+8+4 旧格式仍支持（回归）
    check("6+8+4 (PEAC) 412702********2432",
          is_valid_chinese_id("412702********2432"))

    # 完整 18 位仍支持（回归）
    check("完整 18 位 513024196202082552",
          is_valid_chinese_id("513024196202082552"))

    # 无效
    check("14+X 而非 * (无效)",
          not is_valid_chinese_id("51102519741110XXX"))
    check("13+5 而非 14+4 (无效)",
          not is_valid_chinese_id("5110251974111*****"))

    # extract_chinese_id_from_text
    text = "11\n张三\n身份证\n51102519741110****\n1990-01-01"
    ids = extract_chinese_id_from_text(text)
    check("extract_chinese_id_from_text 14+4 提取",
          ids == ["51102519741110****"], f"got {ids}")

    # 混合 14+4 + 完整 18 位
    text = "A\n51102519741110****\nB\n510224197809113274"
    ids = extract_chinese_id_from_text(text)
    check("混合 14+4 + 完整 18 位提取",
          set(ids) == {"51102519741110****", "510224197809113274"},
          f"got {ids}")


def test_inline_extractor_14_4():
    """inline_extractor._ID_REGEX 支持 14+4 格式"""
    from insurance_agent.extractors.inline_extractor import InlineExtractor

    regex = InlineExtractor._ID_REGEX
    test_cases = [
        ("51102519741110****", "14+4"),
        ("412702********2432", "6+8+4"),
        ("513024196202082552", "完整 18 位"),
    ]
    for tid, desc in test_cases:
        m = regex.search(tid)
        check(f"_ID_REGEX 匹配 {desc} ({tid})",
              m is not None and m.group(0) == tid,
              f"got {m.group(0) if m else None}")


def test_continuation_page_14_4():
    """metadata_extractor_node._is_list_continuation_page 支持 14+4 续页"""
    from insurance_agent.agents.invoice_recognition.nodes.metadata_extractor_node import (
        MetadataExtractorNode,
    )

    # 14+4 三人续页 → True
    text_14_4 = """
11
张三
身份证
51102519741110****
1990-01-01
12
李四
身份证
51102519920304****
1992-03-04
13
王五
身份证
51102519950305****
1995-03-05
"""
    check("14+4 续页（3 IDs）识别为清单续页",
          MetadataExtractorNode._is_list_continuation_page(text_14_4))

    # 仅 2 个 ID → False
    text_14_4_v2 = """
1
张三
身份证
51102519741110****
2
李四
身份证
51102519920304****
"""
    check("14+4 续页（2 IDs）不视为清单续页",
          not MetadataExtractorNode._is_list_continuation_page(text_14_4_v2))

    # 完整 18 位回归
    text_full = """
1
张三
身份证
513024196202082552
2
李四
身份证
510224197809113274
3
王五
身份证
511023196805207918
"""
    check("完整 18 位续页（3 IDs）识别为清单续页（回归）",
          MetadataExtractorNode._is_list_continuation_page(text_full))


def test_table_extractor_xclass_job_title():
    """table_extractor 正确分离 occupation_class 和 job_title"""
    import fitz
    from insurance_agent.extractors.table_extractor import TableExtractor

    pdf_path = Path(__file__).resolve().parents[1] / "data" / "policy_pdfs" / \
        "电子保单_成都林盛鑫屹园林绿化工程有限公司_小微_12652416800201450969_lnl.pdf"
    if not pdf_path.exists():
        print(f"⚠️ PDF 不存在: {pdf_path}, 跳过端到端测试")
        return

    doc = fitz.open(pdf_path)
    # page 4 包含前 17 人
    text = doc[3].get_text()

    extractor = TableExtractor()
    persons = extractor.extract(text, policy_holder='成都林盛鑫屹园林绿化工程有限公司')
    doc.close()

    check(f"提取人数 = 17 (page 4 范围)",
          len(persons) == 17, f"got {len(persons)}")

    if not persons:
        return

    # 第一人：刘敏
    p0 = persons[0]
    check("第 1 人姓名 = 刘敏",
          p0.name == '刘敏', f"got {p0.name!r}")
    check("第 1 人 14+4 脱敏 ID 51102519741110****",
          p0.id_number == '51102519741110****', f"got {p0.id_number!r}")
    # 关键：job_title 应该是"绿化栽植工"，不是"三类职业绿化栽植工"
    check("第 1 人 job_title = 绿化栽植工（不被三类职业污染）",
          p0.job_title == '绿化栽植工', f"got {p0.job_title!r}")
    check("第 1 人 occupation_class = 三类",
          p0.occupation_class == '三类', f"got {p0.occupation_class!r}")


def test_pingan_property_end_to_end():
    """端到端测试：上传 PDF → 23 人入库"""
    import requests

    pdf_path = Path(__file__).resolve().parents[1] / "data" / "policy_pdfs" / \
        "电子保单_成都林盛鑫屹园林绿化工程有限公司_小微_12652416800201450969_lnl.pdf"
    if not pdf_path.exists():
        print(f"⚠️ PDF 不存在: {pdf_path}, 跳过端到端测试")
        return

    try:
        r = requests.get('http://127.0.0.1:8765/api/health', timeout=3)
        if r.status_code != 200:
            print(f"⚠️ 服务未运行 (status={r.status_code}), 跳过端到端测试")
            return
    except Exception as e:
        print(f"⚠️ 服务连接失败: {e}, 跳过端到端测试")
        return

    with open(pdf_path, 'rb') as f:
        files = {'file': (pdf_path.name, f, 'application/pdf')}
        r = requests.post('http://127.0.0.1:8765/api/upload',
                          files=files, data={'policy_type_hint': '主保单'},
                          timeout=180)

    check("端到端 status=200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code != 200:
        return

    body = r.json()
    result = body['results'][0]
    check(f"23 人全部提取 (got {body['total_persons']})",
          body['total_persons'] == 23)
    check("保险公司识别 = 中国平安",
          result['insurance_company'] == '中国平安',
          f"got {result['insurance_company']!r}")
    check("保单号 = 12652416800201450969",
          result['policy_number'] == '12652416800201450969',
          f"got {result['policy_number']!r}")

    # 第一人：刘敏
    p0 = result['persons'][0]
    check("端到端 第 1 人姓名 = 刘敏",
          p0['name'] == '刘敏', f"got {p0['name']!r}")
    check("端到端 第 1 人 14+4 脱敏 ID 51102519741110****",
          p0['id_number'] == '51102519741110****', f"got {p0['id_number']!r}")
    check("端到端 第 1 人 job_title = 绿化栽植工（不再三类职业绿化栽植工）",
          p0['job_title'] == '绿化栽植工', f"got {p0['job_title']!r}")
    check("端到端 第 1 人 occupation_class = 三类",
          p0.get('occupation_class') == '三类',
          f"got {p0.get('occupation_class')!r}")


def test_placeholder_protects_xclass():
    """回归测试：X类职业的占位符保护机制"""
    # 模拟完整预处理流程
    test_text = '51102519741110****\n三类职业\n绿化栽植工'

    _PLACEHOLDER = '\ue000'  # U+E000 私有区字符
    # 步骤 1: 占位符
    test_text = re.sub(
        r'([一二三四五六七八九十])\s*类\s*职\s*业',
        lambda m: m.group(1) + '类职业' + _PLACEHOLDER,
        test_text,
    )
    check("占位符机制：三类职业后插入 \ue000",
          test_text == '51102519741110****\n三类职业\ue000\n绿化栽植工',
          f"got {test_text!r}")

    # 步骤 2: 合并跨行工种（4b）
    test_text = re.sub(
        r'((?!是|否|有|无)[\u4e00-\u9fff（])\n((?!雇员|员工|人员)[\u4e00-\u9fff]{1,8}(?:工|员|师|者|人))',
        r'\1\2',
        test_text,
    )
    check("占位符机制：4b 不再合并职业 + 绿化栽植工",
          test_text == '51102519741110****\n三类职业\ue000\n绿化栽植工',
          f"got {test_text!r}")

    # 步骤 3: 还原占位符
    test_text = test_text.replace(_PLACEHOLDER, '')
    check("占位符机制：还原后保持原格式",
          test_text == '51102519741110****\n三类职业\n绿化栽植工',
          f"got {test_text!r}")


if __name__ == "__main__":
    print("=" * 72)
    print("平安产险『电子保单_雇主安心保-四川』新格式适配回归测试")
    print("=" * 72)
    print()

    test_masked_id_pattern_14_4()
    print()
    test_inline_extractor_14_4()
    print()
    test_continuation_page_14_4()
    print()
    test_placeholder_protects_xclass()
    print()
    test_table_extractor_xclass_job_title()
    print()
    test_pingan_property_end_to_end()
    print()

    print("=" * 72)
    print(f"通过: {passed}/{passed+failed} | 失败: {failed}/{passed+failed}")
    print("=" * 72)

    sys.exit(0 if failed == 0 else 1)