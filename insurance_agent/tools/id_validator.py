"""身份证通用工具

可复用于任何需要校验/提取身份证号的场景。

身份证结构（18位）：
- 前6位  区域码
- 接下来8位 出生日期 (YYYYMMDD)
- 接下来3位 顺序码
- 最后1位 校验码 (0-9 或 X)

校验策略：
1. 区域码前缀必须合法（11-65/71/81/82/91）
2. 出生日期必须合理（1940-当前年+1）
3. 长度必须为 18
"""

import re
from typing import Optional

# 合法区域码前 2 位（中国行政区划前缀）
VALID_AREA_PREFIXES = {
    "11", "12", "13", "14", "15",
    "21", "22", "23",
    "31", "32", "33", "34", "35", "36", "37",
    "41", "42", "43", "44", "45", "46",
    "50", "51", "52", "53", "54",
    "61", "62", "63", "64", "65",
    "71",
    "81", "82",
    "91",
}

# 严格身份证正则：6位地区码 + 4位年 + 2位月 + 2位日 + 3位顺序 + 1位校验
# 年份: 1940-2039 (19[4-9]\d 或 20[0-3]\d)
_ID_PATTERN = re.compile(
    r"(\d{6})(19[4-9]\d|20[0-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]"
)


def normalize_id(raw: str) -> str:
    """统一身份证格式：去空白、X 转大写"""
    return raw.strip().upper()


def is_valid_chinese_id(raw: str) -> bool:
    """校验是否为中国大陆居民身份证号

    校验维度：
    1. 长度 18
    2. 区域码前缀合法
    3. 出生日期范围合理
    """
    if not raw:
        return False
    text = raw.strip()
    if len(text) != 18:
        return False

    m = _ID_PATTERN.fullmatch(text)
    if not m:
        return False

    prefix = text[:2]
    if prefix not in VALID_AREA_PREFIXES:
        return False

    year = int(m.group(2))
    if year < 1940 or year > 2030:
        return False

    return True


def extract_chinese_id_from_text(text: str) -> list[str]:
    """从一段文本中提取所有合法的身份证号"""
    if not text:
        return []

    results = []
    for m in _ID_PATTERN.finditer(text):
        candidate = m.group(0)
        if is_valid_chinese_id(candidate):
            results.append(normalize_id(candidate))
    return results
