"""通用中文姓名提取工具

策略：在给定文本中找到最像 2-4 字中文人名的片段，并过滤常见非名字词。
"""

import re
from typing import Optional

# 2-4 字中文字符串
_CN_NAME_CANDIDATE = re.compile(r"[\u4e00-\u9fff]{2,4}")

# 常见非姓名词（持续扩充）
_NON_NAME_WORDS = {
    "身份证", "证件", "雇员", "序号", "姓名", "性别", "年龄",
    "职业", "等级", "参保", "计划", "用工", "单位", "岗位",
    "起期", "止期", "道路", "绿化", "工", "类", "号",
    "保单", "保险", "清单", "人员", "雇员", "说明",
    "销售", "渠道", "代理", "经纪", "广东", "美保",
    "签章", "系统", "打印", "盖章", "投保",
    "安装", "结构", "钢", "劳务", "建筑", "工程",
    "装饰", "有限", "公司", "责任", "条款",
    "普通", "绿化工", "道路绿化工", "钢结构安装工",
    "高处", "作业", "普通道路",
    "身份证号", "证件号", "证件号码", "证件类型",
}


def extract_chinese_name(text: str) -> Optional[str]:
    """从文本中提取最可能的中文人名（取最后一个候选）"""
    if not text:
        return None

    candidates = _CN_NAME_CANDIDATE.findall(text)
    valid = [c for c in candidates if c not in _NON_NAME_WORDS and 2 <= len(c) <= 4]
    if not valid:
        return None
    return valid[-1]


def extract_names_near(text: str, anchor_pos: int, window: int = 100) -> list[str]:
    """在 anchor_pos 附近提取所有可能是人名的候选"""
    if not text:
        return []

    start = max(0, anchor_pos - window)
    region = text[start:anchor_pos]

    candidates = _CN_NAME_CANDIDATE.findall(region)
    return [c for c in candidates if c not in _NON_NAME_WORDS and 2 <= len(c) <= 4]
