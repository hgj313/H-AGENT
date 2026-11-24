# -*- coding: utf-8 -*-
"""保单号 / 批单号 的号段规则（正则交叉校验用）

**只作用于保单号与批单号两个字段**，人员信息不走这里（人员一律由 AI 提取）。

为什么要独立于 `MetadataExtractorNode._extract_policy_numbers`
------------------------------------------------------
原函数靠**标签**匹配（"保险单号："、"批单号："）来区分主/批单号，但现实中有两类漏网：

1. **标签同名**：太保批单 PDF 里主保单号与批单号都印成「保险单号：」，
   靠标签无法区分 —— 实测「批单-重庆华诚屹-BSHH01137126QA1S4T6Y.pdf」：
   第 1/2/3 页是 `保险单号：ASHH07037126FT001LPW`（主），
   第 14 页附加条款是 `保险单号：BSHH01137126QA1S4T6Y`（批）。
   原函数因此只取到主保单号，批单号丢失。

2. **文件名用连字符分隔**：`批单-公司名-BSHH...pdf`，
   原 `parse_policy_filename` 只认 `_` / 空格 分隔 → 提取不到号。

号段前缀是承保机构发行的**硬证据**（比标签可靠）：
- 太保：``ASHH`` = 主保单（A=Annual）、``BSHH`` = 批单（B=Batch）
- 利宝/太保：``81``/``8116`` = 主、``71``/``7116`` = 批
- 众安：``PS`` = 主、``PE`` = 批
- 国寿：``202666...`` = 主、``2026G01...`` = 批
"""

import re
from typing import List, Tuple

# 号段前缀 → 类型（"主"=主保单号，"批"=批单号）
# 顺序敏感：长前缀在前，避免 "202666" 抢占 "2026G01"
_PREFIX_RULES: List[Tuple[str, str]] = [
    # 太保
    ("BSHH", "批"),
    ("ASHH", "主"),
    ("SHBX", "主"),
    ("X44", "主"),
    # 众安在线
    ("PE07", "批"),
    ("PS07", "主"),
    ("PS08", "主"),
    ("PE08", "批"),
    # 国寿（业务凭证号=批单号）
    ("2026G01", "批"),
    ("202666", "主"),
    # 利宝 / 太保
    ("81160", "主"),
    ("71160", "批"),
    ("61160", "批"),
    # 华安 / 北部湾 / 平安养老 / 大地 / 申能 / 阳光 / 黄河
    ("613010104", "主"),
    ("804147", "主"),
    ("PEAC", "主"),
    ("PZFZ", "主"),
    ("6513", "主"),
    ("HGC", "主"),
    ("HL11", "主"),
    ("6622902", "主"),
]

# 通用：纯数字号段的首位判断（8 开头=主，7 开头=批）
_DIGIT_LEAD_RULES = {"8": "主", "7": "批"}

# 号段最小长度（太短容易把金额、年份、页码误当号）
_MIN_NO_LEN = 12

_BATCH_NAME_PATTERN = re.compile(r"批单|批改|替换|批增|批减")


def classify_by_prefix(no: str) -> str:
    """按号段前缀判断类型，返回 "主" / "批" / "" """
    if not no:
        return ""
    up = no.upper().lstrip()
    for prefix, kind in _PREFIX_RULES:
        if up.startswith(prefix):
            return kind
    if up.isdigit():
        return _DIGIT_LEAD_RULES.get(up[0], "")
    return ""


def extract_numbers_from_filename(file_name: str) -> Tuple[str, str]:
    """从文件名提取（主保单号, 批单号）

    支持 `保单_公司_号` / `保单-公司-号` / `公司_号_BD` / `批单-公司-号` 等。

    Returns:
        (main_no, batch_no)
    """
    if not file_name:
        return "", ""
    name = re.sub(r"\.(pdf|PDF)$", "", file_name)

    candidates = re.findall(r"[A-Za-z0-9]{%d,}" % _MIN_NO_LEN, name)
    if not candidates:
        return "", ""

    is_batch_name = bool(_BATCH_NAME_PATTERN.search(name))

    main_no = batch_no = ""
    for cand in candidates:
        kind = classify_by_prefix(cand)
        if kind == "批" and not batch_no:
            batch_no = cand
        elif kind == "主" and not main_no:
            main_no = cand
        elif not kind:
            if is_batch_name:
                if not batch_no:
                    batch_no = cand
            elif not main_no:
                main_no = cand

    # 批单文件且只解析出一个号 → 该号是批单号（主保单号需从正文找）
    if is_batch_name and main_no and not batch_no:
        batch_no = main_no
        main_no = ""
    # 主保单文件但号段被判成批 → 纠正
    if not is_batch_name and batch_no and not main_no:
        main_no = batch_no
        batch_no = ""

    return main_no, batch_no


def extract_numbers_from_text(text: str) -> Tuple[str, List[str]]:
    """从正文提取号段

    Returns:
        (标签语义下的批单号（无则空）, 全部「保险单号」标签下的号列表)
    """
    if not text:
        return "", []

    batch_labels = (
        r"批单号码[：:\s]*([A-Z0-9]{12,30})",
        r"批单号[：:\s]*([A-Z0-9]{12,30})",
        r"业务凭证号[：:\s]*([A-Z0-9]{12,30})",
    )

    batch_no = ""
    for p in batch_labels:
        m = re.search(p, text)
        if m:
            batch_no = m.group(1)
            break

    all_nos: List[str] = []
    for m in re.finditer(r"保险单号[：:\s]*([A-Z0-9]{12,30})", text):
        no = m.group(1)
        if no not in all_nos:
            all_nos.append(no)

    return batch_no, all_nos


def resolve_policy_numbers(text: str, file_name: str = "") -> Tuple[str, str, str]:
    """综合「正文标签 + 号段前缀 + 文件名」判定 (主保单号, 批单号, 类型)

    类型返回 "主保单" / "批单"。
    """
    file_main, file_batch = extract_numbers_from_filename(file_name)
    tag_batch, all_nos = extract_numbers_from_text(text)

    text_main = ""
    text_batch = ""
    for no in all_nos:
        kind = classify_by_prefix(no)
        if kind == "主" and not text_main:
            text_main = no
        elif kind == "批" and not text_batch:
            text_batch = no

    # 正文里只出现一个号时按号段特征定归属
    if not text_main and not text_batch and all_nos:
        only = all_nos[0]
        kind = classify_by_prefix(only)
        if kind == "主":
            text_main = only
        elif kind == "批":
            text_batch = only

    if tag_batch:
        text_batch = tag_batch

    main_no = file_main or text_main
    batch_no = file_batch or text_batch

    # 兜底：正文里有多个号
    if main_no and not batch_no:
        for no in all_nos:
            if no != main_no and classify_by_prefix(no) == "批":
                batch_no = no
                break
    if batch_no and not main_no:
        for no in all_nos:
            if no != batch_no and classify_by_prefix(no) == "主":
                main_no = no
                break

    # 类型判定
    is_batch = bool(batch_no)
    if not is_batch:
        if _BATCH_NAME_PATTERN.search(file_name or ""):
            is_batch = True
        elif text and ("批单号" in text or "业务凭证号" in text):
            is_batch = True

    policy_type = "批单" if is_batch else "主保单"
    return main_no, batch_no, policy_type
