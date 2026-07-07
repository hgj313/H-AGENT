"""身份证号补全工具

当 PDF 本身对身份证号脱敏（如 342225********6613）时，
利用人员的出生日期补全被屏蔽的出生日期段（第 7-14 位），
并重新计算校验码（第 18 位）。

身份证结构（18 位）：
- 第 1-6 位   区域码
- 第 7-14 位  出生日期 YYYYMMDD  ← 脱敏通常覆盖此段
- 第 15-17 位 顺序码
- 第 18 位    校验码 (0-9 或 X)

校验码算法：
- 权重: [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
- 和 = sum(前17位数字 * 对应权重)
- 取模 11，映射: 0→1, 1→0, 2→X, 3→9, 4→8, 5→7, 6→6, 7→5, 8→4, 9→3, 10→2
"""

import re
from typing import Optional

# 校验码权重（位置 1-17，0-indexed 0-16）
_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]

# 校验码映射表
_CHECKSUM_MAP = {
    0: "1", 1: "0", 2: "X", 3: "9", 4: "8",
    5: "7", 6: "6", 7: "5", 8: "4", 9: "3", 10: "2",
}

# 匹配脱敏身份证号：18 位，包含 *
_MASKED_ID_PATTERN = re.compile(r"^(\d{6})\*+(\d{0,4})$")


def calculate_checksum(id17: str) -> str:
    """计算身份证校验码（第 18 位）

    Args:
        id17: 身份证前 17 位数字字符串

    Returns:
        校验码字符 ('0'-'9' 或 'X')
    """
    if len(id17) != 17 or not id17.isdigit():
        return ""

    total = sum(int(id17[i]) * _WEIGHTS[i] for i in range(17))
    return _CHECKSUM_MAP[total % 11]


def parse_birth_date(raw: str) -> Optional[str]:
    """将各种日期格式统一为 YYYYMMDD

    支持格式：
    - 1990-03-07 / 1990-3-7
    - 19900307
    - 1990年03月07日 / 1990年3月7日
    - 1990/03/07 / 1990/3/7

    Returns:
        YYYYMMDD 字符串，或 None（无法解析）
    """
    if not raw:
        return None

    s = raw.strip()

    # 纯数字 8 位
    if re.fullmatch(r"\d{8}", s):
        year, month, day = int(s[:4]), int(s[4:6]), int(s[6:8])
        if 1940 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
            return s
        return None

    # YYYY-MM-DD / YYYY/MM/DD
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1940 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}{mo:02d}{d:02d}"
        return None

    # YYYY年MM月DD日
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1940 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}{mo:02d}{d:02d}"
        return None

    return None


def is_masked_id(id_number: str) -> bool:
    """判断身份证号是否被脱敏（包含 * 号）"""
    if not id_number:
        return False
    return "*" in id_number


def reconstruct_masked_id(masked_id: str, birth_date: str) -> tuple[str, bool]:
    """用出生日期补全被脱敏的身份证号

    策略：
    1. 身份证第 7-14 位 (0-indexed 6-13) 是出生日期 YYYYMMDD
    2. 将脱敏的 * 替换为出生日期对应位
    3. 重新计算第 18 位校验码

    Args:
        masked_id: 脱敏身份证号（含 *），如 "342225********6613"
        birth_date: 出生日期（各种格式均可）

    Returns:
        (reconstructed_id, success)
        - reconstructed_id: 补全后的身份证号；失败时返回原值
        - success: 是否成功补全
    """
    if not masked_id or not is_masked_id(masked_id):
        return masked_id, True  # 无需补全

    birth_str = parse_birth_date(birth_date)
    if not birth_str:
        return masked_id, False  # 出生日期不可用

    masked_id = masked_id.strip().upper()
    chars = list(masked_id)

    # 填充出生日期段（位置 6-13）
    birth_filled = True
    for i in range(6, 14):
        if i >= len(chars):
            birth_filled = False
            break
        if chars[i] == "*":
            chars[i] = birth_str[i - 6]
        elif chars[i] != birth_str[i - 6]:
            # 可见位与出生日期不符 — 可能出生日期识别有误
            birth_filled = False
            break

    if not birth_filled:
        return masked_id, False

    # 填充后检查是否还有未替换的 *（在出生日期段之外）
    remaining_stars = [i for i, c in enumerate(chars) if c == "*"]

    if remaining_stars:
        # 顺序码段 (14-16) 仍有 *：无法补全
        if any(14 <= i <= 16 for i in remaining_stars):
            return masked_id, False

        # 仅校验码 (17) 为 *：直接重新计算
        if remaining_stars == [17]:
            id17 = "".join(chars[:17])
            checksum = calculate_checksum(id17)
            if checksum:
                chars[17] = checksum
                return "".join(chars), True
            return masked_id, False

        # 其他情况：无法补全
        return masked_id, False

    # 全部 * 已替换：验证校验码
    id17 = "".join(chars[:17])
    correct_checksum = calculate_checksum(id17)
    if not correct_checksum:
        return masked_id, False

    # 如果校验码位也是 * 或不匹配，用计算值替换
    if chars[17] == "*" or chars[17].upper() != correct_checksum:
        chars[17] = correct_checksum

    return "".join(chars), True


def reconstruct_persons_ids(persons: list) -> list[str]:
    """批量补全人员列表中的脱敏身份证号

    遍历所有 InsuredPerson，对含 * 的身份证号尝试用 birth_date 补全。
    返回补全过程中产生的警告信息列表。

    Args:
        persons: InsuredPerson 列表（原地修改 id_number）

    Returns:
        warnings: 警告信息列表
    """
    warnings = []

    for p in persons:
        if not is_masked_id(p.id_number):
            continue

        if not p.birth_date:
            warnings.append(f"身份证号被脱敏但缺少出生日期: {p.name} (ID={p.id_number})")
            continue

        original = p.id_number
        reconstructed, success = reconstruct_masked_id(p.id_number, p.birth_date)

        if success:
            p.id_number = reconstructed
            if original != reconstructed:
                warnings.append(f"身份证号已补全: {p.name} ({original} → {reconstructed})")
        else:
            warnings.append(f"身份证号补全失败: {p.name} (ID={p.id_number}, birth={p.birth_date})")

    return warnings
