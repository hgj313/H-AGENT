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

# 2026-10-08 新增：平安产险 PDF 中脱敏格式"51102519741110****"
# 6位地区码 + 4位年 + 2位月 + 2位日 (共14位) + 4星(顺序+校验位)
# 同样总长 18 字符，* 占末尾顺序/校验段
_MASKED_ID_PATTERN_TAIL = re.compile(r"(\d{14})\*{4}")

# 2026-10-27 新增：平安产险"平安放心意外尊享方案(互联网版)"脱敏格式
# "41**************16" = 2位省代码 + 14星 + 2位校验段
# ⚠️ 与"统一社会信用代码"（91**************89）格式完全相同，必须靠前置标签区分
# ⚠️ 末位校验码可能是 X（如 "34**************5X"），必须允许 [\dX]
_MASKED_ID_PATTERN_SHORT = re.compile(r"(\d{2})\*{14}([\dX]{2})")

# 通用匹配（任一脱敏格式）：6地区+6-10星+0-4位 或 14位+4星 或 2位+14星+2位
_MASKED_ID_PATTERN_GENERIC = re.compile(
    r"(?:\d{6}\*{6,10}\d{0,4}[\dXx]?|\d{14}\*{4}|\d{2}\*{14}[\dX]{2})"
)

# 非身份证证件标签：出现在脱敏号码前时，该号码不是身份证
# （统一社会信用代码 / 营业执照号 / 护照号 / 组织机构代码等均可能是 18 位星号格式）
_NON_ID_LABEL_PATTERN = re.compile(
    r"(统一社会信用代码|营业执照号|组织机构代码|纳税人识别号|"
    r"护照号码|港澳通行证|台湾居民通行证|军官证|士兵证|"
    r"社保号|公积金号|统一编号)[\s:：]*$"
)


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

    # 2. 2026-10-08 新增：脱敏格式"6地区码+4年+2月+2日+4星"（平安产险）
    #    例如 "51102519741110****"，总长 18，* 占末尾顺序/校验段
    m_masked_tail = _MASKED_ID_PATTERN_TAIL.fullmatch(text)
    if m_masked_tail:
        prefix = text[:2]
        return prefix in VALID_AREA_PREFIXES

    # 3. 2026-10-27 新增：脱敏格式"2位省代码+14星+2位"（平安产险互联网版）
    #    例如 "41**************16"，总长 18
    m_masked_short = _MASKED_ID_PATTERN_SHORT.fullmatch(text)
    if m_masked_short:
        prefix = text[:2]
        return prefix in VALID_AREA_PREFIXES

    # 4. 完整格式：6位地区 + YYYYMMDD + 3位顺序 + 1位校验
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


def _is_non_id_labeled(text: str, start: int) -> bool:
    """判断号码前是否紧跟非身份证证件标签

    2026-10-27：平安产险"平安放心意外尊享方案(互联网版)"中，投保人的
    统一社会信用代码 "91**************89" 与被保险人身份证 "41**************16"
    格式完全相同（2位+14星+2位，总长18）。唯一可靠的区分依据是前置标签：
    身份证前是"身份证"，统一社会信用代码前是"统一社会信用代码"。

    Args:
        text: 完整文本
        start: 号码在文本中的起始位置

    Returns:
        True = 该号码是其他证件号（应排除），False = 可能是身份证
    """
    # 取号码前 30 个字符，剥掉换行后检查末尾是否是非身份证标签
    prefix = text[max(0, start - 30):start]
    prefix = re.sub(r"[\s\r\n]+", "", prefix)
    return bool(_NON_ID_LABEL_PATTERN.search(prefix))


def extract_chinese_id_with_positions(text: str) -> list[tuple[str, int]]:
    """提取所有身份证号及其在文本中的起始位置（2026-10-27 新增）

    为什么需要位置信息：
    脱敏精度不足时，不同人的脱敏身份证号可能**完全相同**。
    例：平安产险"平安放心意外尊享方案(互联网版)"中
        张超   → 34**************18
        蔡明明 → 34**************18
    只返回 ID 列表时无法区分二人（会漏掉第 5 人并把名字错配给第 2 人）。
    返回 (id, start_pos) 让调用方能按出现顺序逐个定位。

    与 extract_chinese_id_from_text 的匹配规则完全一致（同一套正则 + 同一套
    非身份证标签排除逻辑），但**保留重复项**（按位置区分），不按 ID 去重。

    Returns:
        [(id_number, start_pos), ...] 按在文本中的出现顺序排列
    """
    if not text:
        return []

    results: list[tuple[str, int]] = []
    full_id_positions = {(m.start(), m.end()) for m in _ID_PATTERN.finditer(text)}

    # 脱敏匹配（三种格式），按位置排序保证输出顺序与文本顺序一致
    masked_matches = (
        list(_MASKED_ID_PATTERN.finditer(text))
        + list(_MASKED_ID_PATTERN_TAIL.finditer(text))
        + list(_MASKED_ID_PATTERN_SHORT.finditer(text))
    )
    masked_matches.sort(key=lambda m: m.start())

    seen_spans: set[tuple[int, int]] = set()

    for m in _ID_PATTERN.finditer(text):
        candidate = m.group(0)
        if is_valid_chinese_id(candidate):
            results.append((normalize_id(candidate), m.start()))
            seen_spans.add((m.start(), m.end()))

    for m in masked_matches:
        span = (m.start(), m.end())
        if span in seen_spans:
            continue
        candidate = m.group(0)
        if not is_valid_chinese_id(candidate):
            continue
        # 排除统一社会信用代码等其他证件类型
        if _is_non_id_labeled(text, m.start()):
            continue
        # 与已有完整 ID 重叠则跳过
        if any(s <= m.start() < e or s < m.end() <= e for s, e in full_id_positions):
            continue
        results.append((normalize_id(candidate), m.start()))
        seen_spans.add(span)

    results.sort(key=lambda x: x[1])
    return results


def extract_chinese_id_from_text(text: str) -> list[str]:
    """从一段文本中提取所有合法的身份证号（支持完整 / 脱敏多种格式）

    2026-09-24 增强：识别形如 "412702********2432" 的脱敏身份证号。
    2026-10-08 增强：识别形如 "51102519741110****" 的脱敏身份证号（平安产险）。
    2026-10-27 增强：识别形如 "41**************16" 的脱敏身份证号（平安产险互联网版），
                    并排除前置标签为"统一社会信用代码"等其他证件类型的同格式号码。
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

    # 收集已匹配的完整 ID 位置（用于去重）
    full_id_positions = {(m.start(), m.end()) for m in _ID_PATTERN.finditer(text)}

    # 再匹配脱敏身份证（按位置去重，避免重叠匹配）
    # 2026-10-08 重构：合并两种脱敏格式（_MASKED_ID_PATTERN + _MASKED_ID_PATTERN_TAIL）
    # 2026-10-27 再加 _MASKED_ID_PATTERN_SHORT（2位+14星+2位）
    masked_matches = (
        list(_MASKED_ID_PATTERN.finditer(text))
        + list(_MASKED_ID_PATTERN_TAIL.finditer(text))
        + list(_MASKED_ID_PATTERN_SHORT.finditer(text))
    )

    if not results:
        # 完全没匹配到完整 ID 时直接用脱敏
        for m in masked_matches:
            candidate = m.group(0)
            if not is_valid_chinese_id(candidate):
                continue
            # 2026-10-27：排除统一社会信用代码等其他证件类型
            if _is_non_id_labeled(text, m.start()):
                continue
            results.append(normalize_id(candidate))
    else:
        # 已匹配到一些完整 ID，用脱敏 pattern 找不重叠的
        for m in masked_matches:
            candidate = m.group(0)
            if not is_valid_chinese_id(candidate):
                continue
            # 2026-10-27：排除统一社会信用代码等其他证件类型
            if _is_non_id_labeled(text, m.start()):
                continue
            # 检查是否与已有完整 ID 重叠
            if any(s <= m.start() < e or s < m.end() <= e for s, e in full_id_positions):
                continue
            results.append(normalize_id(candidate))
    return results
