"""通用公司名提取工具

支持形式：
- 完整："重庆森炜建筑劳务有限公司" / "太平洋财产保险股份有限公司"
- 标签后："投保人名称：成都兴久隆钢结构工程有限公司"
"""

import re
from typing import Optional

# 匹配完整公司名（含有限公司/集团/股份/责任等常见后缀）
_COMPANY_PATTERN = re.compile(
    r"([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))"
)

# 标签后提取（如 "投保人名称：XXX" / "投保人名称 XXX"）
# 说明：
#   - 大多数保单标签后可能是冒号或空格（如"投保人名称 杭州班王..."），故允许 [：:\s]*。
#   - 唯独通用 "投保人" 标签必须紧跟冒号（投保人[：:]\s*），否则会误匹配条款文字，
#       例："投保人向中国太平洋财产保险股份有限公司……提交书面投保申请" 中
#       "投保人向" 之间无冒号，不应被识别为投保人公司名。
_LABEL_PATTERNS = [
    re.compile(r"投保人名称[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))"),
    re.compile(r"被保险人名称[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))"),
    # 被保人（太平洋批单等用"被保人："，且可能后跟英文标签如"Name of Insured："）
    re.compile(r"被保人[：:\s]*[A-Za-z\s:：]*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))"),
    # 名称：最通用（太平洋保单"● 投保人信息 / 名称：XXX" / "被保险人信息 / 名称：XXX"）
    re.compile(r"名称[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))"),
    # 通用"投保人"标签：必须紧跟冒号，避免误匹配条款文字（见上说明）
    re.compile(r"投保人[：:]\s*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))"),
    re.compile(r"用工单位[：:\s]*([\u4e00-\u9fff]+(?:有限公司|集团(?:公司)?|股份有限公司|责任公司|公司))"),
]

# 误报黑名单：这些不是公司名
_FALSE_POSITIVES = {
    "本公司", "保险公司", "保险人公司", "该公司", "此公司",
    "鉴于投保人已向本公司", "向本公司",
}


def _is_valid_company_name(name: str) -> bool:
    """判断是否为有效的公司名（排除误报）"""
    if not name:
        return False
    if name in _FALSE_POSITIVES:
        return False
    # 以"本公司"结尾的不是公司名
    if name.endswith("本公司"):
        return False
    # 太短（少于4个字）且以"公司"结尾的可能是误报
    if len(name) < 5 and name.endswith("公司"):
        return False
    return True


def extract_company_name(text: str) -> Optional[str]:
    """从文本中提取第一个有效公司名"""
    if not text:
        return None

    for m in _COMPANY_PATTERN.finditer(text):
        name = m.group(1)
        if _is_valid_company_name(name):
            return name
    return None


def extract_company_after_label(text: str) -> Optional[str]:
    """从带标签的文本中提取公司名（如 "投保人名称：XXX"）"""
    if not text:
        return None

    for pattern in _LABEL_PATTERNS:
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            if _is_valid_company_name(name):
                return name
    return None
