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

# 中介/经纪公司黑名单：这些是"代为投保"的机构，不是用工单位（投保人）
# 场景：保单由保险经纪公司代理投保时，PDF"投保人名称"位置写的是经纪公司名
# 但业务上我们需要的是真正雇员工的公司（用工单位），不是中介
# 处理方式：识别时跳过这种名字，回退到下一条或报错让用户确认
_INTERMEDIARY_KEYWORDS = (
    "保险经纪",   # 广东美保保险经纪有限公司
    "经纪公司",
    "代理公司",
    "保险代理",
    "保险公估",
    "保险经纪机构",
)


def _is_intermediary_company(name: str) -> bool:
    """判断是否为保险中介公司（保险经纪/代理/公估等），不应作为投保人/用工单位使用。"""
    if not name:
        return False
    return any(kw in name for kw in _INTERMEDIARY_KEYWORDS)


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
    """从带标签的文本中提取公司名（如 "投保人名称：XXX"）

    跳过中介/经纪公司（保险经纪/代理/公估等），因为这些是"代为投保"的中介，
    不是真正的用工单位。返回 None 时调用方可回退到其他来源（如文件名解析）。
    """
    if not text:
        return None

    for pattern in _LABEL_PATTERNS:
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            if _is_intermediary_company(name):
                # 跳过中介公司，继续匹配下一个标签
                continue
            if _is_valid_company_name(name):
                return name
    return None


# 保单号前缀 → 保险公司号段映射（2026-09-16 新增，号段兜底防御）
# 保单号前缀是承保机构发行的硬证据，比 PDF 文本中关键词匹配更可靠。
# 用于华安批单088 类场景：PDF 文本提到"黄河"被错误识别，但保单号 613010104 是华安号段。
_POLICY_NUMBER_PREFIX_TO_COMPANY = {
    "613010104": "华安财产保险",       # 华安财险号段（杭州班王 088 批单证实）
    "8116013100": "利宝保险",           # 利宝主保单号段（81 开头）
    "7116013100": "利宝保险",           # 利宝批单号段（71 开头）
    "ASHH": "安诚财产保险",             # 安诚 ASHH 开头
    "81160": "安诚财产保险",            # 安诚 81160 号段
    "61160": "安诚财产保险",            # 安诚 61160 号段（批单）
    "X44": "中国太平洋财产保险",        # 太保 X44 开头
    "SHBX": "中国太平洋财产保险",       # 太保 SHBX 开头
}


def detect_insurance_company_by_policy_number(policy_number: str) -> str:
    """根据保单号前缀反查保险公司（2026-09-16 新增，号段兜底）

    保单号前缀是承保机构发行的硬证据，比 PDF 文本中关键词匹配更可靠。
    用于覆盖文本检测结果（如华安批单088 的 PDF 文本提到"黄河"但保单号段是华安）。

    Args:
        policy_number: 保单号（主保单或批单号均可）

    Returns:
        匹配到的保险公司名（标准名），未匹配返回空字符串
    """
    if not policy_number:
        return ""
    pn_upper = policy_number.upper()
    for prefix, company in _POLICY_NUMBER_PREFIX_TO_COMPANY.items():
        if pn_upper.startswith(prefix.upper()):
            return company
    return ""
