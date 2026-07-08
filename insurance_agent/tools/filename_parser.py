"""文件名解析工具

解析保单/批单 PDF 文件名，提取：
- policy_type: 保单 / 批单
- company: 所属公司名称
- policy_number: 保单号（如果文件名中包含）

支持的文件名格式：
1. 标准格式: 保单_公司名_保单号.pdf  /  批单_公司名_保单号.pdf
2. 粤灿格式: 替换4人保单·粤灿0612.pdf  /  替换9人·批增2人保单·广州粤灿0624.pdf
3. 简单格式: 南京大千装饰工程有限公司保单.pdf
"""

import re
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class FilenameInfo:
    """文件名解析结果"""
    file_name: str = ""
    policy_type: str = ""        # "保单" / "批单"
    company: str = ""            # 所属公司名称
    policy_number: str = ""      # 保单号（文件名中包含时）
    raw_company: str = ""        # 原始公司名片段（未标准化）


def parse_policy_filename(file_path: str) -> FilenameInfo:
    """解析保单/批单文件名

    Args:
        file_path: 文件完整路径或文件名

    Returns:
        FilenameInfo: 解析结果
    """
    file_name = os.path.basename(file_path)
    # 去掉扩展名
    name_no_ext = os.path.splitext(file_name)[0]

    info = FilenameInfo(file_name=file_name)

    # --- 格式1: 标准格式 保单_公司名_保单号 ---
    # 例: 保单_深圳市祥胜建设有限公司_668701202644017100008803
    #     批单_重庆选鹏建筑工程有限公司_7116013100260058791001
    #     保单_兴文县欣雅建筑劳务有限公司_ASHH07037126FN004NXB(1)
    #     电子保单+广州市粤灿建设工程有限公司+X44061701260000083506
    #     保单_重庆森得尔劳务有限公司_8116013100260068880000(2)
    m = re.match(
        r"^(?:电子)?(保单|批单)[_\s+](.+?)[_\s+]([A-Za-z0-9]+)",
        name_no_ext,
    )
    if m:
        info.policy_type = m.group(1)
        info.company = m.group(2).strip()
        info.policy_number = m.group(3).strip()
        info.raw_company = info.company
        return info

    # --- 格式2: 粤灿格式 替换X人保单·公司名日期 ---
    # 例: 替换4人保单·粤灿0612
    #     替换3人保单·广州粤灿0601
    #     替换9人·批增2人保单·广州粤灿0624
    m = re.match(
        r"^替换\d+人(?:·批增\d+人)?保单·(.+?)(\d{4})$",
        name_no_ext,
    )
    if m:
        info.policy_type = "批单"
        info.raw_company = m.group(1).strip()
        # 尝试从公司名中提取实际公司名
        # "广州粤灿" → "粤灿" (去掉地名前缀)
        # 但保留完整名作为 company
        info.company = info.raw_company
        return info

    # --- 格式3: 简单格式 公司名保单 ---
    # 例: 南京大千装饰工程有限公司保单
    if name_no_ext.endswith("保单"):
        company_part = name_no_ext[:-2].strip()
        if company_part:
            info.policy_type = "保单"
            info.company = company_part
            info.raw_company = company_part
            return info

    # --- 兜底: 检测关键词 ---
    if "批单" in name_no_ext or "替换" in name_no_ext:
        info.policy_type = "批单"
    elif "保单" in name_no_ext:
        info.policy_type = "保单"

    # 尝试从文件名中提取公司名
    company_match = re.search(
        r"([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))",
        name_no_ext,
    )
    if company_match:
        info.company = company_match.group(1)
        info.raw_company = info.company

    return info


def is_main_policy(file_path: str) -> bool:
    """判断是否为主保单文件（而非批单）"""
    info = parse_policy_filename(file_path)
    return info.policy_type == "保单"


def is_endorsement(file_path: str) -> bool:
    """判断是否为批单文件"""
    info = parse_policy_filename(file_path)
    return info.policy_type == "批单"


def extract_company_from_filename(file_path: str) -> str:
    """从文件名中提取公司名"""
    return parse_policy_filename(file_path).company
