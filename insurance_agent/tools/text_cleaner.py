"""通用 PDF 文本清洗工具

pymupdf 提取的文本中常含 ￿ / � / 0x0C 等不可见字符。

已知坑：pymupdf 的 get_text("text") 模式会把部分 CJK 标点
（全角冒号、半角全角标点等）映射到 PUA（U+E000-U+F8FF），
然后用 \\uffff 占位。需要在 cleaner 里做"还原"。

清洗规则：
- 把 \\uffff 占位还原为最可能的中文标点（全角冒号 / 顿号 / 引号）
- 去除 0x0C 换页符
- 去除 NBSP 替换为普通空格
- 压缩连续 ASCII 空白
"""


# 保单里出现频率最高的 PUA 占位对应的标点
_PUA_REPLACEMENTS = {
    "\uffff": "：",  # 全角冒号 (最常见)
}


def clean_pdf_text(raw: str) -> str:
    """清洗 PDF 文本"""
    if not raw:
        return ""

    text = raw
    # 1. 把 \uffff 占位还原为最可能的中文标点
    for bad, good in _PUA_REPLACEMENTS.items():
        text = text.replace(bad, good)

    # 2. 去除 0x0C 换页符
    text = text.replace("\x0c", " ")
    # 3. 去除 NBSP 替换为普通空格
    text = text.replace("\xa0", " ")
    # 4. 仅压缩 ASCII 空白（不用 str.split() 以免误吃全角标点）
    import re as _re
    text = _re.sub(r"[ \t\f\v]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    return text.strip()
