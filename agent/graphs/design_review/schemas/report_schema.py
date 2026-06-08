"""对比审查报告的输出 Schema。

使用 Pydantic v2 定义 `GenerateComparativeReport` 及其子结构，配合
`BaseChatModel.bind_tools([GenerateComparativeReport], tool_choice="required", strict=True)`
约束大模型严格按 JSON 结构返回。

对应 prompt: GENERATE_COMPARISON_REPORT_PROMPT
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── 报告元数据 ──────────────────────────────────────────────────────────
class ReportMeta(BaseModel):
    """报告元信息"""

    report_id: str = Field(default="", description="报告编号，格式 DR-YYYYMMDD-HHmmss-XXXX")
    generated_at: str = Field(default="", description="ISO8601 生成时间戳")
    prd_source: str = Field(default="", description="PRD 文档标识")
    prototype_source: str = Field(default="", description="原型图标识")
    standard_source: str = Field(default="", description="标准文档标识")
    total_items: int = Field(default=0, description="总检查项数")
    compliance_rate: float = Field(default=0.0, description="合规率 (pass / total_items)")


# ── 汇总统计 ──────────────────────────────────────────────────────────
class SummaryByOutcome(BaseModel):
    """按判定结果统计"""

    pass_count: int = Field(default=0, alias="pass", description="通过项数")
    deviation: int = Field(default=0, description="偏差项数")
    violation: int = Field(default=0, description="违反项数")
    missing: int = Field(default=0, description="缺失项数")
    unspecified: int = Field(default=0, description="未规定项数")
    prd_override: int = Field(default=0, description="PRD 自定义项数")


class SummaryBySeverity(BaseModel):
    """按严重等级统计"""

    critical: int = Field(default=0, description="强违规数")
    major: int = Field(default=0, description="重要违规数")
    minor: int = Field(default=0, description="建议违规数")
    info: int = Field(default=0, description="仅记录数")


class CategoryStats(BaseModel):
    """单一类别的合规统计"""

    total: int = Field(default=0, description="该类别总项数")
    pass_count: int = Field(default=0, alias="pass", description="该类别通过项数")
    compliance_rate: float = Field(default=0.0, description="该类别合规率")


class Summary(BaseModel):
    """报告汇总"""

    by_outcome: SummaryByOutcome = Field(default_factory=SummaryByOutcome)
    by_severity: SummaryBySeverity = Field(default_factory=SummaryBySeverity)
    by_category: Dict[str, CategoryStats] = Field(default_factory=dict)


# ── 单条检查项 ─────────────────────────────────────────────────────────
class StandardValue(BaseModel):
    """标准规格值"""

    value: str = Field(default="", description="标准具体值")
    raw_value: str = Field(default="", description="标准原始值")
    is_mandatory: bool = Field(default=False, description="是否强规")
    severity: str = Field(default="", description="严重等级：critical/major/minor/info")
    is_unspecified: bool = Field(default=False, description="标准是否未明确")


class PrdValue(BaseModel):
    """PRD 规格值"""

    value: str = Field(default="", description="PRD 具体值")
    exists: bool = Field(default=False, description="PRD 是否存在该规格")
    matches_standard: bool = Field(default=False, description="PRD 值是否与标准一致")


class PrototypeValue(BaseModel):
    """原型图实现值"""

    value: str = Field(default="", description="原型具体值")
    exists: bool = Field(default=False, description="原型是否存在该规格")
    matches_standard: bool = Field(default=False, description="原型值是否与标准一致")


class CheckItem(BaseModel):
    """单条检查项"""

    item_id: str = Field(default="", description="检查项编号，格式 ITEM-001")
    dimension_key: str = Field(default="", description="规格维度 key")
    category: str = Field(default="", description="所属类别")
    context: str = Field(default="", description="使用场景/位置")
    standard: StandardValue = Field(default_factory=StandardValue)
    prd: PrdValue = Field(default_factory=PrdValue)
    prototype: PrototypeValue = Field(default_factory=PrototypeValue)
    outcome: str = Field(
        default="",
        description="判定结果：pass/deviation/violation/missing/unspecified/prd_override",
    )
    severity: str = Field(default="", description="严重等级：critical/major/minor/info")
    diff_summary: str = Field(default="", description="差异说明")
    suggestion: str = Field(default="", description="整改建议")
    expected_value: str = Field(default="", description="期望整改后的目标值")
    is_strong_violation: bool = Field(default=False, description="是否为强规违反")


# ── Top Issues ────────────────────────────────────────────────────────
class TopIssue(BaseModel):
    """Top 问题"""

    rank: int = Field(default=0, description="排名")
    dimension_key: str = Field(default="", description="规格维度 key")
    category: str = Field(default="", description="所属类别")
    severity: str = Field(default="", description="严重等级")
    outcome: str = Field(default="", description="判定结果")
    summary: str = Field(default="", description="问题摘要")
    suggestion: str = Field(default="", description="整改建议")


# ── 整改任务 ──────────────────────────────────────────────────────────
class ActionItem(BaseModel):
    """整改任务"""

    task_id: str = Field(default="", description="任务编号，格式 ACT-001")
    title: str = Field(default="", description="任务标题")
    dimension_key: str = Field(default="", description="规格维度 key")
    severity: str = Field(default="", description="严重等级")
    responsible_role: str = Field(default="", description="负责角色")
    action: str = Field(default="", description="具体操作")
    deadline_hint: str = Field(default="", description="截止时间提示")
    status: str = Field(default="todo", description="状态：todo/in_progress/done")


# ── 图表数据 ──────────────────────────────────────────────────────────
class BarChart(BaseModel):
    """柱状图"""

    type: str = Field(default="bar", description="图表类型")
    x_axis: List[str] = Field(default_factory=list, description="X 轴分类")
    y_axis_compliance_rate: List[float] = Field(
        default_factory=list, description="Y 轴合规率"
    )
    unit: str = Field(default="%", description="单位")
    title: str = Field(default="", description="图表标题")


class PieSlice(BaseModel):
    """饼图切片"""

    name: str = Field(default="", description="切片名称")
    value: int = Field(default=0, description="切片值")


class PieChart(BaseModel):
    """饼图"""

    type: str = Field(default="pie", description="图表类型")
    data: List[PieSlice] = Field(default_factory=list, description="切片数据")
    title: str = Field(default="", description="图表标题")


class RadarChart(BaseModel):
    """雷达图"""

    type: str = Field(default="radar", description="图表类型")
    indicators: List[str] = Field(default_factory=list, description="指标名")
    values: List[int] = Field(default_factory=list, description="指标值")
    title: str = Field(default="", description="图表标题")


class CategoryCharts(BaseModel):
    """图表数据集合"""

    compliance_rate_chart: BarChart = Field(default_factory=BarChart)
    outcome_pie: PieChart = Field(default_factory=PieChart)
    severity_radar: RadarChart = Field(default_factory=RadarChart)


# ── 渲染提示 ──────────────────────────────────────────────────────────
class TableColumn(BaseModel):
    """表格列定义"""

    key: str = Field(default="", description="字段 key")
    title: str = Field(default="", description="列标题")
    width: int = Field(default=0, description="列宽 px")
    color_map: Optional[Dict[str, str]] = Field(
        default=None, description="值→颜色映射（可选）"
    )


class DefaultFilter(BaseModel):
    """默认筛选条件"""

    severity: List[str] = Field(default_factory=list, description="默认筛选严重等级")
    outcome: List[str] = Field(default_factory=list, description="默认筛选判定结果")


class RenderHints(BaseModel):
    """前端渲染提示"""

    table_columns: List[TableColumn] = Field(default_factory=list, description="表格列定义")
    default_filter: DefaultFilter = Field(default_factory=DefaultFilter)
    sort_by: str = Field(default="severity", description="默认排序字段")
    sort_order: str = Field(default="asc", description="默认排序方向")


# ── 顶层报告 ──────────────────────────────────────────────────────────
class GenerateComparativeReport(BaseModel):
    """合规审查报告（顶层结构）"""

    report_meta: ReportMeta = Field(default_factory=ReportMeta)
    summary: Summary = Field(default_factory=Summary)
    items: List[CheckItem] = Field(default_factory=list, description="检查项明细")
    top_issues: List[TopIssue] = Field(
        default_factory=list, description="Top 问题（最多 10 条）"
    )
    action_items: List[ActionItem] = Field(
        default_factory=list, description="整改任务清单"
    )
    category_charts: CategoryCharts = Field(default_factory=CategoryCharts)
    render_hints: RenderHints = Field(default_factory=RenderHints)


__all__ = [
    "GenerateComparativeReport",
    "ReportMeta",
    "SummaryByOutcome",
    "SummaryBySeverity",
    "CategoryStats",
    "Summary",
    "StandardValue",
    "PrdValue",
    "PrototypeValue",
    "CheckItem",
    "TopIssue",
    "ActionItem",
    "BarChart",
    "PieSlice",
    "PieChart",
    "RadarChart",
    "CategoryCharts",
    "TableColumn",
    "DefaultFilter",
    "RenderHints",
]
