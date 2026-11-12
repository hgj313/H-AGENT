"""混合「增保/减保」批单的**行级**判定回归测试

来源：黄河财产保险批单「替换1人-深圳春羽园林工程有限公司1112」
- 批单号：662290212192026BZN00000765-008
- 《雇员变动清单》表头：序号|姓名|证件号|职业代码|职业/工种|状态|备注
- 第 1 行 杨廷林 532625198302112510 → 状态「删除」→ 减保
- 第 2 行 李运容 452428196804142022 → 状态「新增」→ 增保

Bug 现象
--------
第 2 行（新增）被误判为「减保」。

根因
----
`TableExtractor` 的 pre_region 会回溯到**上一个身份证号之后**，
post_region 截断到**下一个身份证号之前**。
黄河《雇员变动清单》的「状态」列在「证件号」列**右侧**，
所以第 2 行的 pre_region 里装的是**第 1 行**的状态单元格（"删除"），
而第 2 行自己的状态（"新增"）在 post_region 里。

原实现把 pre_region + post_region 拼成一个字符串做「减保优先」的全局扫描
→ 两个标记同时存在时，"删除" 抢先命中 → 第 2 行被判成减保。

修复
----
`_detect_row_modification_type_by_column`：
表头在 PDF 文本里按从左到右出现，比较「状态/变动类型」列名与「证件号」列名的
先后位置 → 还原左右关系 → 决定本行状态取 pre_region 还是 post_region。

⚠️ 只有「同时命中增标记和减标记」的歧义场景才启用消歧，单标记场景行为完全不变。
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from insurance_agent.extractors.table_extractor import TableExtractor  # noqa: E402


# ════════════════════════════════════════════════════════════
# 1. 状态列侧别判定
# ════════════════════════════════════════════════════════════


def test_status_column_after_id_column():
    """黄河《雇员变动清单》：状态列在证件号列右侧"""
    text = (
        "《雇员变动清单》\n"
        "序号\n姓名\n证件号\n职业代码\n职业/工种\n状态\n备注\n"
        "1\n杨廷林\n532625198302112510\n31010\n20014\n农夫\n删除\n"
    )
    te = TableExtractor()
    assert te._detect_status_column_side(text) == "after"


def test_status_column_before_id_column():
    """中国人寿《被保险人变动清单》：变动类型列在证件号码列左侧"""
    text = (
        "《被保险人变动清单》\n"
        "序号是否生效变动类型被保险人类型姓名个人编号生效日终止日证件号码\n"
        "1是增加主被保险人张三1234567890123456782026-07-31\n"
    )
    te = TableExtractor()
    assert te._detect_status_column_side(text) == "before"


def test_status_column_side_unknown_without_header():
    """没有表头列名 → 无法判定 → 返回空串（调用方回退原逻辑）"""
    te = TableExtractor()
    assert te._detect_status_column_side("姓名：张三 身份证号：110101199001011234") == ""


# ════════════════════════════════════════════════════════════
# 2. 行级消歧（核心回归）
# ════════════════════════════════════════════════════════════


def _huanghe_rows():
    """黄河批单《雇员变动清单》两行数据（文本形态与 PDF 抽取一致）"""
    header = (
        "批单\n险种：\n雇主责任保险\n投保人：\n深圳春羽园林工程有限公司\n"
        "保单号码：662290212192026BZN00000765\n被保险人：深圳春羽园林工程有限公司\n"
        "批单号码：662290212192026BZN00000765-008\n批文：\n"
        "根据投保人/被保险人申请，保险人同意，自2026年11月13日零时起，"
        "至 2026年11月13日 二十四时止，662290212192026BZN00000765保险单内容变更如下\n"
        "《标的信息》\n \n 本次批改合计加收保费CNY0.00\n"
        "《雇员变动清单》\n"
        "序号\n姓名\n证件号\n职业代码\n职业/工种\n状态\n备注\n"
    )
    row1 = "1\n杨廷林\n532625198302112510\n31010\n20014\n农夫\n删除\n"
    row2 = "2\n李运容\n452428196804142022\n31010\n20014\n农夫\n新增\n"
    tail = "加收保费CNY0.00\n其他事项不变，特此批改。\n签单机构：黄河财产保险股份有限公司\n"
    return header, row1, row2, tail


def _split_rows(text):
    """按身份证号把文本切成 (pre, post) 两段（模拟 extractor 的 region 切分）"""
    ids = ["532625198302112510", "452428196804142022"]
    out = []
    for idn in ids:
        id_pos = text.find(idn)
        raw_post = text[id_pos:id_pos + 400]
        nxt = len(raw_post)
        for other in ids:
            if other == idn:
                continue
            p = raw_post.find(other, 18)
            if 0 < p < nxt:
                nxt = p
        post = raw_post[:nxt]
        prev_b = max(0, id_pos - 200)
        for other in ids:
            if other == idn:
                continue
            p = text.rfind(other, 0, id_pos)
            if p > 0:
                prev_b = max(prev_b, p + 18)
        out.append((text[prev_b:id_pos], post))
    return out


def test_mixed_add_remove_rows_are_distinguished():
    """核心回归：一增一减必须分别判定（修复前第 2 行被误判为减保）"""
    header, row1, row2, tail = _huanghe_rows()
    text = header + row1 + row2 + tail
    te = TableExtractor()

    (pre1, post1), (pre2, post2) = _split_rows(text)

    # 第 1 行：状态「删除」在 post_region
    got1 = te._detect_row_modification_type_by_column(pre1, post1, text)
    assert got1 == "减保", f"第 1 行（删除）应判减保，实际 {got1}"

    # 第 2 行：状态「新增」在 post_region，而 pre_region 里是第 1 行的「删除」
    assert "删除" in pre2, "前提：第 2 行的 pre_region 应含第 1 行的状态单元格"
    assert "新增" in post2, "前提：第 2 行的 post_region 应含本行状态"

    got2 = te._detect_row_modification_type_by_column(pre2, post2, text)
    assert got2 == "增保", f"第 2 行（新增）应判增保，实际 {got2}"


def test_bug_reproduces_on_old_logic():
    """确认旧逻辑确实会误判（证明本测试真的覆盖了这个 bug）"""
    header, row1, row2, tail = _huanghe_rows()
    text = header + row1 + row2 + tail
    te = TableExtractor()
    (pre1, post1), (pre2, post2) = _split_rows(text)

    old1 = te._detect_row_modification_type(pre1 + post1)
    old2 = te._detect_row_modification_type(pre2 + post2)

    assert old1 == "减保"
    assert old2 == "减保", "旧逻辑下第 2 行确实是减保（这就是要修的 bug）"


def test_single_marker_rows_unchanged():
    """单标记场景行为完全不变（严禁影响现有功能）"""
    te = TableExtractor()
    # 只有减保标记 → 减保
    assert te._detect_row_modification_type_by_column(
        "本期减少被保险人：李四", "身份证号 110101199002022345", ""
    ) == "减保"
    # 只有增保标记 → 增保
    assert te._detect_row_modification_type_by_column(
        "本期增加被保险人：张三", "身份证号 110101199002022345", ""
    ) == "增保"
    # 无任何标记 → 空（交由文件级兜底）
    assert te._detect_row_modification_type_by_column(
        "姓名：张三", "身份证号 110101199002022345", ""
    ) == ""


def test_chinalife_before_id_column_keeps_pre_region():
    """中国人寿（变动类型列在证件号左侧）→ 取 pre_region 的标记"""
    te = TableExtractor()
    header = (
        "《被保险人变动清单》\n"
        "序号是否生效变动类型被保险人类型姓名个人编号生效日终止日证件号码\n"
    )
    # 第 2 行：pre_region 含本行「增加」，post_region 含下一行「减少」
    pre = "2是增加主被保险人李四2026-07-31\n"
    post = "3是减少主被保险人王五2026-07-31\n"
    text = header + "1是减少主被保险人张三2026-07-31110101199001011234\n" + pre + "110101199002022345\n" + post

    got = te._detect_row_modification_type_by_column(pre, post, text)
    assert got == "增保", f"中国人寿格式应取 pre_region 的「增加」，实际 {got}"


def test_first_marker_in_prefers_standalone_cell():
    """独立单元格形态的标记优先于正文散文里的同义词"""
    te = TableExtractor()
    # 散文里先出现「减少」，后面才是独立单元格的「新增」
    region = "本次批改减少部分人员\n新增\n"
    assert te._first_marker_in(region, prefer_standalone=True) == "增保"
    # 不要求独立形态时，取最先出现的
    assert te._first_marker_in(region) == "减保"


def test_first_marker_handles_concatenated_cell():
    """单元格拼接形态（如「增加主被保险人」）也能正确识别"""
    te = TableExtractor()
    assert te._first_marker_in("2是增加主被保险人李四\n") == "增保"


# ════════════════════════════════════════════════════════════
# 3. 端到端（真实 PDF，文件不存在则跳过）
# ════════════════════════════════════════════════════════════


def test_real_huanghe_pdf_end_to_end():
    """真实 PDF：TableExtractor 必须把 2 人分别判成 减保 / 增保"""
    pdf_path = Path(
        r"C:\Users\Administrator\Downloads\替换1人-深圳春羽园林工程有限公司1112(1).pdf"
    )
    if not pdf_path.exists():
        pytest.skip(f"PDF 不存在: {pdf_path}")

    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    text = "\n".join(page.get_text() for page in doc)
    doc.close()

    te = TableExtractor()
    persons = te.extract(text, policy_holder="深圳春羽园林工程有限公司")

    assert len(persons) == 2, f"期望 2 人，实际 {len(persons)}"

    by_id = {p.id_number: p for p in persons}
    yang = by_id.get("532625198302112510")
    li = by_id.get("452428196804142022")

    assert yang is not None, "未提取到杨廷林"
    assert li is not None, "未提取到李运容"

    assert yang.modification_type == "减保", f"杨廷林应为减保，实际 {yang.modification_type}"
    assert li.modification_type == "增保", f"李运容应为增保，实际 {li.modification_type}"

    assert yang.name == "杨廷林"
    assert li.name == "李运容"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
