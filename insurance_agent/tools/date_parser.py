"""通用日期解析工具

支持多种保单中出现的日期表述形式：
- 自2026年06月17日0时起至2026年09月16日24时止
- 自2026年06月24日 00时00分00秒起至2026年09月24日 00时00分00秒止
- 2026-06-24 00:00:00
"""

import re
from typing import Optional

# 整体保险期间：自 X年Y月Z日 ... 起至 X年Y月Z日 ... 止
_OVERALL_PATTERNS = [
    re.compile(
        r"自(\d{4})年(\d{1,2})月(\d{1,2})日[\d:时分秒\s]*起[,，]?\s*至(\d{4})年(\d{1,2})月(\d{1,2})日[\d:时分秒\s]*止"
    ),
    re.compile(
        r"自(\d{4})-(\d{1,2})-(\d{1,2})[\s\d:]*起至(\d{4})-(\d{1,2})-(\d{1,2})[\s\d:]*止"
    ),
    re.compile(
        r"保险期间[：:\s]*自(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})[日\s\d:]*至(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})"
    ),
    re.compile(
        r"自(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})日?[\s\d:]*起[,，\s]*至(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})日?[\s\d:]*止"
    ),
]

# 单点日期：2026-06-24 00:00:00  / 2026年06月24日  / 2026年7月1日
_DATE_PATTERN = re.compile(
    r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})[日\s]*(?:\d{1,2}[时:]\d{1,2}(?:分:?\d{1,2}秒?)?)?"
)


def normalize_date(year: str, month: str, day: str) -> str:
    """统一日期格式为 YYYY-MM-DD"""
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def extract_overall_insurance_period(text: str) -> tuple[Optional[str], Optional[str]]:
    """从一段文本中提取整体保险期间

    Returns:
        (start_date, end_date) - 任一未找到则返回 None
    """
    if not text:
        return None, None

    for pattern in _OVERALL_PATTERNS:
        m = pattern.search(text)
        if m:
            return normalize_date(m.group(1), m.group(2), m.group(3)), \
                   normalize_date(m.group(4), m.group(5), m.group(6))
    return None, None


def extract_dates_near(text: str, anchor_pos: int, window: int = 300) -> list[str]:
    """在文本中 anchor_pos 附近提取日期"""
    if not text:
        return []

    start = max(0, anchor_pos - window)
    end = min(len(text), anchor_pos + window)
    region = text[start:end]

    results = []
    for m in _DATE_PATTERN.finditer(region):
        results.append(normalize_date(m.group(1), m.group(2), m.group(3)))
    return results
