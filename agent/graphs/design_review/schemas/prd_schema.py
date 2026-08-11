"""PRD 分析的输出 Schema。

使用 Pydantic v2 定义 `PRDAnalysis` 及其子结构，配合
`BaseChatModel.with_structured_output(PRDAnalysis)` 约束大模型严格按 JSON
结构返回。
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class DocMeta(BaseModel):
    """文档概览"""

    name: str = Field(default="", description="文档名称/版本")
    structure: List[str] = Field(default_factory=list, description="章节目录")
    target_users: List[str] = Field(default_factory=list, description="目标用户")
    background: str = Field(default="", description="业务背景")


class ModuleItem(BaseModel):
    """功能模块"""

    name: str = Field(default="", description="模块名")
    parent: Optional[str] = Field(default=None, description="父模块名")
    features: List[str] = Field(default_factory=list, description="核心功能点")
    dependencies: List[str] = Field(default_factory=list, description="依赖模块")


class PageItem(BaseModel):
    """页面"""

    name: str = Field(default="", description="页面名称")
    type: str = Field(
        default="",
        description="页面类型：列表页/详情页/表单页/统计页/其他",
    )
    jumps_to: List[str] = Field(default_factory=list, description="跳转目标页面")


class FlowItem(BaseModel):
    """关键业务流程"""

    name: str = Field(default="", description="流程名")
    description: str = Field(default="", description="流程描述")
    node_pages: List[str] = Field(default_factory=list, description="涉及页面")
    exception_handling: List[str] = Field(
        default_factory=list,
        description="异常处理：暂存/撤回/重新申请/作废等",
    )


class FieldSpec(BaseModel):
    """字段定义"""

    name: str = Field(default="", description="字段名")
    type: str = Field(default="", description="类型")
    format: str = Field(default="", description="格式")
    rules: str = Field(default="", description="校验规则")
    required: bool = Field(default=False, description="是否必填")


class DataFormat(BaseModel):
    """数据格式"""

    currency_symbol: str = Field(default="", description="货币符号")
    decimal_places: str = Field(default="", description="小数位")
    thousands_separator: bool = Field(default=False, description="是否使用千分位")
    datetime_format: str = Field(default="", description="日期时间格式")
    empty_representation: str = Field(
        default="",
        description="无数据表示方式，如：-- / 0 / 暂无",
    )


class DataPermission(BaseModel):
    """数据权限"""

    org_levels: List[str] = Field(
        default_factory=list,
        description="组织层级：集团→子公司→部门→项目",
    )
    operation_permissions: List[str] = Field(
        default_factory=list, description="操作权限"
    )
    field_permissions: List[str] = Field(default_factory=list, description="字段权限")


class ListSpec(BaseModel):
    """列表页规范"""

    page_size: str = Field(default="", description="每页条数")
    default_sort: str = Field(default="", description="默认排序方式")
    filter_count: str = Field(default="", description="筛选条件数量")
    operations: List[str] = Field(
        default_factory=list,
        description="列表操作：编辑/删除/复制等",
    )


class FormSpec(BaseModel):
    """表单页规范"""

    fields_per_row: str = Field(default="", description="单行字段数")
    label_alignment: str = Field(
        default="",
        description="标签对齐方式：左对齐/右对齐/顶对齐",
    )
    validation_mode: str = Field(default="", description="验证方式：即时/提交")
    after_submit: str = Field(default="", description="提交后行为：跳转/刷新")


class DialogSpec(BaseModel):
    """弹窗规范"""

    types: List[str] = Field(
        default_factory=list, description="弹窗类型：弱提示/强弹窗"
    )
    triggers: List[str] = Field(default_factory=list, description="触发条件")
    close_ways: List[str] = Field(default_factory=list, description="关闭方式")


class StatusDef(BaseModel):
    """状态定义"""

    name: str = Field(default="", description="状态名")
    color: str = Field(default="", description="颜色标识")
    icon: str = Field(default="", description="图标标识")
    transitions: List[str] = Field(default_factory=list, description="状态流转")


class ErrorDef(BaseModel):
    """错误处理"""

    type: str = Field(default="", description="错误类型")
    position: str = Field(default="", description="提示位置")
    style: str = Field(default="", description="提示样式")
    recovery: str = Field(default="", description="恢复方式")


class PerformanceSpec(BaseModel):
    """性能要求"""

    page_load_time: str = Field(default="", description="页面加载时间要求")
    data_volume: str = Field(default="", description="数据量要求")


class SecuritySpec(BaseModel):
    """安全要求"""

    sensitive_fields: List[str] = Field(
        default_factory=list, description="敏感数据标识"
    )
    access_control: List[str] = Field(
        default_factory=list, description="权限控制要求"
    )


class SpecItem(BaseModel):
    """规格值（用于对比报告）"""

    value: str = Field(default="", description="各种UI元素或者操作的规格具体数值或明确值")
    context: str = Field(default="", description="使用场景")


class PRDAnalysis(BaseModel):
    """PRD 分析结果（顶层结构）"""

    overview: DocMeta = Field(default_factory=DocMeta)
    modules: List[ModuleItem] = Field(default_factory=list)
    pages: List[PageItem] = Field(default_factory=list)
    flows: List[FlowItem] = Field(default_factory=list)
    fields: List[FieldSpec] = Field(default_factory=list)
    data_format: DataFormat = Field(default_factory=DataFormat)
    data_permission: DataPermission = Field(default_factory=DataPermission)
    list_spec: ListSpec = Field(default_factory=ListSpec)
    form_spec: FormSpec = Field(default_factory=FormSpec)
    dialog_spec: DialogSpec = Field(default_factory=DialogSpec)
    statuses: List[StatusDef] = Field(default_factory=list)
    errors: List[ErrorDef] = Field(default_factory=list)
    performance: PerformanceSpec = Field(default_factory=PerformanceSpec)
    security: SecuritySpec = Field(default_factory=SecuritySpec)
    potential_issues: List[str] = Field(
        default_factory=list, description="潜在问题"
    )
    to_confirm: List[str] = Field(
        default_factory=list, description="待确认项"
    )
    specs: dict[str, SpecItem] = Field(
        default_factory=dict,
        description='规格值，key 形如 "字体/正文字体"，value 为 {value, context}',
    )
    unspecified_specs: List[str] = Field(
        default_factory=list,
        description="文档中未明确的规格",
    )


__all__ = [
    "DocMeta",
    "ModuleItem",
    "PageItem",
    "FlowItem",
    "FieldSpec",
    "DataFormat",
    "DataPermission",
    "ListSpec",
    "FormSpec",
    "DialogSpec",
    "StatusDef",
    "ErrorDef",
    "PerformanceSpec",
    "SecuritySpec",
    "SpecItem",
    "PRDAnalysis",
]
