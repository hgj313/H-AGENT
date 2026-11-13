"""批单入库守卫（2026-11-13）

背景
----
web_app/server.py 里有一段「批单主保单缺失 → 阻断入库」的防御分支
（2026-09-15 关键防御，源于 森炜 0072423000 批单错填 6894300 日期事件）。
它读取 validator_node 产出的 warnings 来判断。

但 `InvoiceRecognitionState(TypedDict)` 一直没声明 `warnings` 键，
LangGraph 的 `StateGraph` 只会为**已声明**的键建立 channel，
节点返回的 warnings 会被**静默丢弃** → 该防御分支长期是死代码，
从未真正生效过。

2026-11-13 修复透传后它会真正开始执行，而直接启用会造成大面积误拦截：
实测历史 253 个批单中有 43 个（17%、涉及 3953 人）找不到对应主保单，
但这些批单人员在库中的日期缺失数为 0（日期来自清单本身或整体保险期间兜底），
若按「命中告警文本即拦截」处理，这些批单重新上传时会被全部拦下。

因此把判定语义收紧为
    **只有当批单确实会写入空日期记录时才阻断**，
这与防御分支的原始初衷（避免空日期人员记录被 upsert 进库）完全一致。

本模块为**无第三方依赖的纯函数**，便于单测（fastapi 只装在 H-AGENT venv，
项目根 venv 无 fastapi，不能直接 import web_app.server 做单测）。
"""

from typing import Any, Iterable

__all__ = [
    "MAIN_MISSING_WARNING_PATTERNS",
    "find_main_missing_warning",
    "count_missing_date_persons",
    "evaluate_batch_guard",
]

# 命中即视为「批单主保单缺失/不匹配」的告警文本特征
MAIN_MISSING_WARNING_PATTERNS = (
    "未找到对应主保单",
    "主保单号",  # 需与 "不一致" 同时出现，见 find_main_missing_warning
)


def find_main_missing_warning(warnings: Iterable[str] | None) -> str:
    """从 warnings 中找出「批单主保单缺失/不匹配」的告警文本。

    与 web_app 原有过滤条件保持一致：
        "未找到对应主保单" in w  或  ("主保单号" in w 且 "不一致" in w)
    """
    for w in warnings or ():
        if not isinstance(w, str):
            continue
        if "未找到对应主保单" in w:
            return w
        if "主保单号" in w and "不一致" in w:
            return w
    return ""


def count_missing_date_persons(persons: Iterable[dict[str, Any]] | None) -> tuple[int, int]:
    """统计人员中「起止日期缺失」的数量。

    Returns:
        (缺失日期的人数, 总人数)
    """
    total = 0
    missing = 0
    for p in persons or ():
        if not isinstance(p, dict):
            continue
        total += 1
        start = str(p.get("start_date") or "").strip()
        end = str(p.get("end_date") or "").strip()
        if not start or not end:
            missing += 1
    return missing, total


def evaluate_batch_guard(
    warnings: Iterable[str] | None,
    persons: Iterable[dict[str, Any]] | None,
) -> dict[str, Any]:
    """判定一个批单是否应当阻断入库。

    Args:
        warnings: validator_node 产出的告警列表
        persons: extraction_result["insured_persons"]

    Returns:
        {
            "should_block": bool,     # 是否阻断入库
            "reason": str,            # 阻断原因（放行为空）
            "warning": str,           # 命中的主保单缺失告警
            "missing_date_cnt": int,  # 缺日期人数
            "total_persons": int,     # 总人数
        }
    """
    warning = find_main_missing_warning(warnings)
    missing_cnt, total = count_missing_date_persons(persons)

    result = {
        "should_block": False,
        "reason": "",
        "warning": warning,
        "missing_date_cnt": missing_cnt,
        "total_persons": total,
    }

    # 无主保单缺失告警 → 与本次守卫无关
    if not warning:
        return result

    # 没有人员 → 无脏数据风险，放行
    if total == 0:
        return result

    # 人员日期齐全 → 日期另有来源（清单自带 / 整体期间兜底），放行
    if missing_cnt == 0:
        return result

    # 确实会写入空日期记录 → 阻断
    result["should_block"] = True
    result["reason"] = (
        f"批单主保单缺失/不匹配，且 {missing_cnt}/{total} 人缺保险期间，"
        f"拒绝入库（避免写入空日期记录）: {warning}"
    )
    return result
