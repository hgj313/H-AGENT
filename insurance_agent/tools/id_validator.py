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

# 2026-09-24 新增：脱敏（星号遮蔽）身份证号正则
# 平安养老/部分保险公司 PDF 中身份证号以 "412702********2432" 形式出现
# 8 个 * 覆盖出生日期段（pos 6-13），保留 6 位区域码 + 4 位顺序/校验段（pos 14-17）
# 总长 18 字符（与正式身份证号等长），便于入库对齐
_MASKED_ID_PATTERN = re.compile(r"(\d{6})\*{6,10}(\d{2,4}[\dXx]?)")
# 严格 8 星（出生日期段），顺序/校验位可见：
_MASKED_ID_PATTERN_FULL = re.compile(r"(\d{6})\*{8}(\d{3}[\dXx])")


def normalize_id(raw: str) -> str:
    """统一身份证格式：去空白、X 转大写"""
    return raw.strip().upper()


def is_valid_chinese_id(raw: str) -> bool:
    """校验是否为中国大陆居民身份证号（支持完整 / 脱敏两种格式）

    校验维度：
    1. 长度 18（脱敏格式总长仍为 18，* 占出生日期段）
    2. 区域码前缀合法（脱敏时仍可校验）
    3. 出生日期范围合理（脱敏时跳过）
    """
    if not raw:
        return False
    text = raw.strip().upper()
    if len(text) != 18:
        return False

    # 1. 脱敏格式优先匹配：6位地区 + 8星 + 4位可见（含校验位）
    m_masked = _MASKED_ID_PATTERN_FULL.fullmatch(text)
    if m_masked:
        prefix = text[:2]
        return prefix in VALID_AREA_PREFIXES

    # 2. 完整格式：6位地区 + YYYYMMDD + 3位顺序 + 1位校验
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
    """从一段文本中提取所有合法的身份证号（支持完整 / 脱敏两种格式）

    2026-09-24 增强：识别形如 "412702********2432" 的脱敏身份证号。
    保留为原始字符串（含 * 号），不自动用出生日期补全——
    用户的明确指令："身份证号已加密保护，提取出来的身份证也加密保护即可"，
    不应在入库前反推真实身份证号。
    """
    if not text:
        return []

    results = []
    # 先匹配完整身份证
    for m in _ID_PATTERN.finditer(text):
        candidate = m.group(0)
        if is_valid_chinese_id(candidate):
            results.append(normalize_id(candidate))
    # 再匹配脱敏身份证（按位置去重，避免重叠匹配）
    if not results:
        # 完全没匹配到时再尝试脱敏（避免重复扫描）
        for m in _MASKED_ID_PATTERN.finditer(text):
            candidate = m.group(0)
            if is_valid_chinese_id(candidate):
                results.append(normalize_id(candidate))
    else:
        # 已经匹配到一些完整 ID，但仍可能在另一段文本里有脱敏 ID
        # 用脱敏 pattern 找，但只取不与完整 ID 位置重叠的
        id_positions = {(m.start(), m.end()) for m in _ID_PATTERN.finditer(text)}
        for m in _MASKED_ID_PATTERN.finditer(text):
            candidate = m.group(0)
            if not is_valid_chinese_id(candidate):
                continue
            # 检查是否与已有完整 ID 重叠
            if any(s <= m.start() < e or s < m.end() <= e for s, e in id_positions):
                continue
            results.append(normalize_id(candidate))
    return results
