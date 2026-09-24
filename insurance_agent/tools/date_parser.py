"""通用日期解析工具

支持多种保单中出现的日期表述形式：
- 自2026年06月17日0时起至2026年09月16日24时止
- 自2026年06月24日 00时00分00秒起至2026年09月24日 00时00分00秒止
- 2026-06-24 00:00:00
"""

import re
from typing import Optional

# 整体保险期间：自 X年Y月Z日 ... 起至 X年Y月Z日 ... 止
# 字符类包含中文（支持"零时""二十四时"等中文时间表述）
# "自"后允许空格（如"自 2026年03月24日..."）
# 2026-09-22 新增：北部湾格式日期数字间带空格（"2026 年 10 月 01 日"），
#   统一在"年/月/日"两侧加 \s* 容忍空格
_OVERALL_PATTERNS = [
    re.compile(
        r"自\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[\d:时分秒\s\u4e00-\u9fff]*起[,，]?\s*至\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[\d:时分秒\s\u4e00-\u9fff]*止"
    ),
    re.compile(
        r"自\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})[\s\d:时分秒\u4e00-\u9fff]*起?\s*至\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})[\s\d:时分秒\u4e00-\u9fff]*止"
    ),
    re.compile(
        r"保险期间[：:\s]*自\s*(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})[日\s\d:时分秒\u4e00-\u9fff]*至\s*(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})"
    ),
    re.compile(
        r"自\s*(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})日?[\s\d:时分秒\u4e00-\u9fff]*起[,，\s]*至\s*(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})日?[\s\d:时分秒\u4e00-\u9fff]*止"
    ),
    # 2026-09-17 新增：中国人寿"在保名单"绿洲团体意外险 — 整体期限在两条独立字段中
    # 例：保险合同生效日期 2026年06月29日 零时零分零秒 / 保险合同满期日期 2027年06月28日 二十四时
    # 兼容两种字段顺序：生效→满期 或 满期→生效（统一在 _extract_block_kv_period 中处理）
]

# 2026-09-24 新增：平安养老"批改人员清单"格式 — 两条独立字段"保险起期"+"保险止期"
# 例：保险起期（北京时间）：2026 年06 月20 日00 时
#     保险止期（北京时间）：2027 年06 月19 日24 时
# 字段顺序固定为 起期→止期（先起后止）
# 容忍"（北京时间）"括号内中文 + 日期数字间空格
_OVERALL_SEPARATE_FIELDS = re.compile(
    r"保险起期\s*（[^）]*）[：:\s]*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
    r"[\s\d:时分秒\u4e00-\u9fff]*"
    r"\s*保险止期\s*（[^）]*）[：:\s]*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)

# 单点日期：2026-06-24 00:00:00  / 2026/06/24  / 2026年06月24日  / 2026年7月1日
# 2026-09-17 增补：中国人寿"被保险人变动清单"批单使用 YYYY/MM/DD 斜杠分隔（生效日/终止日）
_DATE_PATTERN = re.compile(
    r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日\s]*(?:\d{1,2}[时:]\d{1,2}(?:分:?\d{1,2}秒?)?)?"
)

# 中国人寿"在保名单"绿洲团体意外险 — 两条独立字段（顺序不固定）
# 2026-09-17 新增：处理"保险合同生效日期"和"保险合同满期日期"两条独立字段；
# 字段顺序不固定（PDF 1: 满期→生效；PDF 2: 生效→满期）。
_BLOCK_KV_FIELD_PATTERN = re.compile(
    r"保险合同(?:生效日期|满期日期)[：:\s]*(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})日?"
)


def normalize_date(year: str, month: str, day: str) -> str:
    """统一日期格式为 YYYY-MM-DD"""
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _extract_block_kv_period(text: str) -> tuple[Optional[str], Optional[str]]:
    """提取中国人寿"在保名单"绿洲团体意外险的双字段整体期限

    兼容"保险合同生效日期"和"保险合同满期日期"字段顺序不固定的情况：
    找到所有"保险合同XX日期"字段值，去重后取最早为 start、最晚为 end。
    """
    if not text:
        return None, None
    dates: list[str] = []
    seen: set[str] = set()
    for m in _BLOCK_KV_FIELD_PATTERN.finditer(text):
        d = normalize_date(m.group(1), m.group(2), m.group(3))
        if d not in seen:
            seen.add(d)
            dates.append(d)
    if len(dates) >= 2:
        dates.sort()
        return dates[0], dates[-1]
    if len(dates) == 1:
        # 只有一条 — 不能推断期间
        return dates[0], None
    return None, None


def extract_overall_insurance_period(text: str) -> tuple[Optional[str], Optional[str]]:
    """从一段文本中提取整体保险期间

    Returns:
        (start_date, end_date) - 任一未找到则返回 None
    """
    if not text:
        return None, None

    # 1. 通用正则（支持各种"自X起至Y止"格式）
    for pattern in _OVERALL_PATTERNS:
        m = pattern.search(text)
        if m:
            return normalize_date(m.group(1), m.group(2), m.group(3)), \
                   normalize_date(m.group(4), m.group(5), m.group(6))

    # 2. 平安养老"保险起期/保险止期"两条独立字段
    m = _OVERALL_SEPARATE_FIELDS.search(text)
    if m:
        return normalize_date(m.group(1), m.group(2), m.group(3)), \
               normalize_date(m.group(4), m.group(5), m.group(6))

    # 3. 块状键值对双字段（中国人寿在保名单）
    return _extract_block_kv_period(text)


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
