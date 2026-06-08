"""原型图分析的输出 Schema。

使用 Pydantic v2 定义 `PrototypeAnalysis` 及其子结构，配合
`BaseChatModel.bind_tools([PrototypeAnalysis], tool_choice="required", strict=True)`
约束大模型在 OpenAI / Anthropic 兼容协议下严格按结构化字段返回。
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class PageBaseInfo(BaseModel):
    """页面基础信息"""

    name: str = Field(default="", description="页面名称/标题")
    nav_path: str = Field(default="", description="所属模块/导航路径")
    page_type: str = Field(
        default="",
        description="页面类型：列表页/详情页/表单页/统计页/流程页/其他",
    )
    fidelity: str = Field(default="", description="保真度等级：低/中/高")
    is_flow_page: bool = Field(default=False, description="是否为流程页面")
    min_resolution: str = Field(default="", description="最低适应分辨率，如 1366×768")
    nav_depth: str = Field(default="", description="导航层级数")
    menu_text_length: str = Field(default="", description="导航菜单文案字数限制")


class LayoutNav(BaseModel):
    """布局与导航"""

    layout_form: str = Field(default="", description="整体布局形式")
    top_nav_elements: List[str] = Field(
        default_factory=list, description="顶部导航栏元素"
    )
    left_menu_default: str = Field(
        default="", description="左侧菜单默认状态：展开/收缩"
    )
    has_breadcrumb: bool = Field(default=False, description="是否有面包屑导航")
    multi_table_tabs: bool = Field(
        default=False, description="是否支持多 Table 标签页管理"
    )
    tab_vs_breadcrumb: str = Field(
        default="", description="标签页 vs 面包屑选择"
    )


class ColorSpec(BaseModel):
    """颜色规范"""

    primary: str = Field(default="", description="主色调")
    secondary: str = Field(default="", description="辅助色")
    neutral: str = Field(default="", description="中性色")
    total_count: str = Field(default="", description="页面色系总数")
    supports_dark_mode: bool = Field(
        default=False, description="是否支持主色切换/暗黑模式"
    )
    success: str = Field(default="", description="成功色")
    warning: str = Field(default="", description="警告色")
    error: str = Field(default="", description="错误色")
    link: str = Field(default="", description="链接色")
    disabled: str = Field(default="", description="失效色")


class FontSpec(BaseModel):
    """字体规范"""

    cn_font_windows: str = Field(default="", description="中文字体 Windows")
    cn_font_mac: str = Field(default="", description="中文字体 Mac")
    en_font_windows: str = Field(default="", description="英文字体 Windows")
    en_font_mac: str = Field(default="", description="英文字体 Mac")
    title_size: str = Field(default="", description="主标题字号")
    subtitle_size: str = Field(default="", description="次标题字号")
    body_size: str = Field(default="", description="正文字号")
    helper_size: str = Field(default="", description="辅助字号")
    table_size: str = Field(default="", description="表格内字号")
    disabled_size: str = Field(default="", description="失效字号")
    error_size: str = Field(default="", description="错误字号")


class SpacingComponentSize(BaseModel):
    """间距与组件尺寸"""

    component_spacing: str = Field(default="", description="组件间距规范")
    page_padding: str = Field(default="", description="页面边距")
    card_height_12px: str = Field(default="", description="卡片高度（12px 文字）")
    card_height_16px: str = Field(default="", description="卡片高度（16px 文字）")
    avatar_size: str = Field(default="", description="头像尺寸")
    button_size: str = Field(default="", description="按钮 size，如 middle")
    button_space: str = Field(default="", description="按钮间距 space size")


class IconSpec(BaseModel):
    """图标规范"""

    icon_lib: str = Field(default="", description="图标库：antdesign 线框/双色")
    ali_icon: bool = Field(default=False, description="是否使用 aliIcon 自定义图标库")
    chart_lib: str = Field(default="", description="图表库：ECharts / AntV")


class VisualSpec(BaseModel):
    """视觉规范（聚合）"""

    color: ColorSpec = Field(default_factory=ColorSpec)
    font: FontSpec = Field(default_factory=FontSpec)
    spacing: SpacingComponentSize = Field(default_factory=SpacingComponentSize)
    icon: IconSpec = Field(default_factory=IconSpec)


class ButtonSpec(BaseModel):
    """按钮规范"""

    types: List[str] = Field(
        default_factory=list, description="按钮类型：主按钮/次按钮/文字按钮等"
    )
    size: str = Field(default="", description="按钮 size")
    space_size: str = Field(default="", description="按钮间距 space size")
    list_button_text: str = Field(
        default="", description="列表小按钮（A 标签）字号与字数"
    )
    color_rule: str = Field(default="", description="按钮颜色规则")
    six_states: List[str] = Field(
        default_factory=list,
        description="按钮六状态：正常/聚焦/悬停/激活/加载/禁用",
    )
    has_loading: bool = Field(default=False, description="是否配置 Loading")
    has_debounce: bool = Field(default=False, description="是否配置防抖")


class FieldComponentMap(BaseModel):
    """字段类型与组件映射"""

    money: str = Field(default="", description="金额对应组件")
    number: str = Field(default="", description="数字对应组件")
    text: str = Field(default="", description="文本对应组件")
    textarea: str = Field(default="", description="文本域对应组件")
    richtext: str = Field(default="", description="富文本对应组件")


class FormSpec(BaseModel):
    """表单规范"""

    field_component_map: FieldComponentMap = Field(default_factory=FieldComponentMap)
    placeholder_style: str = Field(default="", description="输入框提示词风格")
    required_mark: str = Field(default="", description="必填标识，如红色 *")
    label_alignment: str = Field(default="", description="标签对齐方式")
    edit_layout: str = Field(default="", description="编辑样式布局")
    detail_layout: str = Field(default="", description="详情样式布局")
    format_validations: List[str] = Field(
        default_factory=list, description="格式校验字段：邮箱/身份证/手机号等"
    )
    validation_modes: List[str] = Field(
        default_factory=list, description="验证方式：即时/提交"
    )
    after_submit: str = Field(default="", description="提交后跳转/刷新要求")
    exit_interaction: str = Field(default="", description="退出交互方式")
    initial_value_clearable: bool = Field(
        default=False, description="初始值是否可手动删除"
    )


class TableSpec(BaseModel):
    """表格规范"""

    column_count: str = Field(default="", description="列数")
    column_titles: List[str] = Field(default_factory=list, description="列标题")
    column_title_length: str = Field(default="", description="列标题字数限制")
    alignments: str = Field(default="", description="对齐方式")
    page_size_default: str = Field(default="", description="默认每页条数")
    page_size_options: List[str] = Field(
        default_factory=list, description="可选每页条数"
    )
    sort_rule: str = Field(default="", description="默认排序规则")
    hscroll_fixed_cols: List[str] = Field(
        default_factory=list, description="横向滚动时固定列"
    )
    vscroll_fixed: List[str] = Field(
        default_factory=list, description="竖向滚动时固定行"
    )
    width_rule: str = Field(default="", description="表格宽度规则")
    component: str = Field(default="", description="表格组件，如 Ptable small")
    has_serial_col: bool = Field(default=False, description="是否有序号列")
    action_col_button_length: str = Field(
        default="", description="操作列按钮字数限制"
    )
    has_zebra_stripe: bool = Field(default=False, description="是否有斑马纹")
    detail_embedded_rows: str = Field(
        default="", description="详情页内嵌表格行数"
    )
    has_status_icon: bool = Field(default=False, description="状态字段是否配颜色图标")
    money_format: str = Field(default="", description="金额格式")
    empty_representation: str = Field(default="", description="无数据表示")
    progress_states: List[str] = Field(
        default_factory=list, description="进度条三状态"
    )
    no_external_scrollbar: bool = Field(
        default=False, description="是否无外部滚动条"
    )
    header_filter_default_off: bool = Field(
        default=False, description="表头筛选默认是否关闭"
    )


class WeakDialog(BaseModel):
    """弱弹窗"""

    toast_types: List[str] = Field(
        default_factory=list, description="Toast 类型：普通/成功/失败/警告"
    )
    toast_duration: str = Field(default="", description="Toast 自动消失时长")
    hover_popover: bool = Field(default=False, description="是否有悬停弹窗")
    color_categories: List[str] = Field(
        default_factory=list, description="颜色分类：error/warning/success"
    )


class StrongDialog(BaseModel):
    """强弹窗"""

    requires_interaction: bool = Field(
        default=False, description="是否必须交互后才能离开"
    )
    has_mask: bool = Field(default=False, description="是否带遮罩层")
    mask_closable: bool = Field(default=False, description="是否点击遮罩关闭")
    center_mode: str = Field(default="", description="居中方式")
    min_ratio: str = Field(default="", description="最小比例")
    draggable: bool = Field(default=False, description="是否支持拖拽")
    within_viewport: bool = Field(default=False, description="是否限制在视口内")


class DialogSpec(BaseModel):
    """弹窗规范（聚合）"""

    weak: WeakDialog = Field(default_factory=WeakDialog)
    strong: StrongDialog = Field(default_factory=StrongDialog)


class FilterSpec(BaseModel):
    """筛选栏规范"""

    default_field_count: str = Field(default="", description="默认展示字段数")
    total_field_count: str = Field(default="", description="总字段数")
    has_more_query: bool = Field(
        default=False, description="是否支持更多查询弹窗"
    )
    query_mode: str = Field(default="", description="查询方式")
    has_single_field_clear: bool = Field(
        default=False, description="是否有单字段清除按钮"
    )
    has_clear_all: bool = Field(default=False, description="是否有一键清除")
    match_types: List[str] = Field(
        default_factory=list, description="模糊查询/精确查询类型"
    )
    supports_multi: bool = Field(default=False, description="是否支持多选")
    has_default_value: bool = Field(default=False, description="是否有默认值带出")
    trims_spaces: bool = Field(default=False, description="是否首尾去空格")
    has_linked_filter: bool = Field(default=False, description="是否支持联动筛选")
    has_cache: bool = Field(default=False, description="是否缓存频繁使用数据")
    has_debounce: bool = Field(default=False, description="筛选操作是否防抖")
    time_format: str = Field(default="", description="时间格式")


class StatCardSpec(BaseModel):
    """统计卡片"""

    count: str = Field(default="", description="卡片数量")
    per_row_count: str = Field(default="", description="单行卡片数")
    row_count: str = Field(default="", description="卡片总行数")
    has_shadow_on_select: bool = Field(
        default=False, description="选中是否加外阴影"
    )


class ComponentSpec(BaseModel):
    """组件规范（聚合）"""

    button: ButtonSpec = Field(default_factory=ButtonSpec)
    form: FormSpec = Field(default_factory=FormSpec)
    table: TableSpec = Field(default_factory=TableSpec)
    dialog: DialogSpec = Field(default_factory=DialogSpec)
    filter: FilterSpec = Field(default_factory=FilterSpec)
    stat_card: StatCardSpec = Field(default_factory=StatCardSpec)


class NavInteractionSpec(BaseModel):
    """导航与快捷入口"""

    max_depth: str = Field(default="", description="导航最大层级")
    extra_level_strategy: str = Field(
        default="", description="多余层级处理：标签页/面包屑"
    )
    has_global_search: bool = Field(default=False, description="是否有菜单全局搜索")
    has_quick_entry: bool = Field(
        default=False, description="是否有首页常用功能快捷入口"
    )


class DebounceSpec(BaseModel):
    """防抖/节流机制"""

    input_change: bool = Field(default=False, description="输入框内容变化防抖")
    button_click: bool = Field(default=False, description="按钮点击防抖")
    window_resize: bool = Field(default=False, description="窗口调整防抖")
    mouse_event: bool = Field(default=False, description="鼠标事件防抖")
    api_merge: bool = Field(default=False, description="API 请求合并防抖")
    async_request: bool = Field(default=False, description="异步请求防抖")


class FilterInteractionSpec(BaseModel):
    """筛选栏交互"""

    has_global_search: bool = Field(default=False, description="全局检索")
    has_single_field_clear: bool = Field(default=False, description="单字段清除")
    manual_update: bool = Field(default=False, description="手动更新查询条件")
    shows_applied_conditions: bool = Field(
        default=False, description="是否展示当前应用条件"
    )
    has_cache: bool = Field(default=False, description="数据缓存")
    has_debounce: bool = Field(default=False, description="防抖处理")
    has_clear_all: bool = Field(default=False, description="清除筛选")
    supports_combine: bool = Field(default=False, description="多条件组合筛选")
    has_default_value: bool = Field(default=False, description="默认值带出")
    trims_spaces: bool = Field(default=False, description="空格处理")


class ListInteractionSpec(BaseModel):
    """列表交互"""

    hover_highlight: bool = Field(default=False, description="悬停高亮")
    click_selected: bool = Field(default=False, description="点击选中")
    chart_hover: bool = Field(default=False, description="图表悬停详情")
    chart_click: bool = Field(default=False, description="图表点击钻取")
    editable: bool = Field(default=False, description="可编辑表格")
    multi_row_edit: bool = Field(default=False, description="多行编辑")
    checkbox_clear_after_submit: bool = Field(
        default=False, description="提交后清除勾选"
    )
    has_copy: bool = Field(default=False, description="复制功能")
    refresh_after_detail_back: bool = Field(
        default=False, description="详情返回后刷新"
    )
    single_row_edit: bool = Field(default=False, description="单行编辑")
    value_copy_trim: bool = Field(default=False, description="字段值复制去空格")
    header_filter_default_off: bool = Field(
        default=False, description="表头筛选默认不展示"
    )


class FormInteractionSpec(BaseModel):
    """表单处理交互"""

    clear_hint: bool = Field(default=False, description="清晰提示")
    exit_interaction: bool = Field(default=False, description="退出交互方式")
    realtime_validate: bool = Field(default=False, description="即时验证")
    highlight_error: bool = Field(default=False, description="错误字段高亮")
    success_tip: bool = Field(default=False, description="成功提示")
    error_style: str = Field(default="", description="错误提示样式")


class MultiQuerySpec(BaseModel):
    """多查询方式并行"""

    has_abort_controller: bool = Field(
        default=False, description="是否使用 AbortController"
    )


class ShortcutSpec(BaseModel):
    """快捷交互"""

    detail_close: List[str] = Field(
        default_factory=list,
        description="详情页关闭方式：点击外部/ESC/关闭按钮",
    )
    entry_close: str = Field(default="", description="数据录入页关闭方式")
    multi_table_tab: List[str] = Field(
        default_factory=list,
        description="多页面 table 标签操作：关闭左/右/其他/刷新当前",
    )
    batch_action: bool = Field(default=False, description="是否有批量操作快捷按钮")


class InteractionSpec(BaseModel):
    """交互规范（聚合）"""

    nav: NavInteractionSpec = Field(default_factory=NavInteractionSpec)
    debounce: DebounceSpec = Field(default_factory=DebounceSpec)
    filter: FilterInteractionSpec = Field(default_factory=FilterInteractionSpec)
    list: ListInteractionSpec = Field(default_factory=ListInteractionSpec)
    form: FormInteractionSpec = Field(default_factory=FormInteractionSpec)
    multi_query: MultiQuerySpec = Field(default_factory=MultiQuerySpec)
    shortcut: ShortcutSpec = Field(default_factory=ShortcutSpec)


class StateSpec(BaseModel):
    """状态定义"""

    data_states: List[str] = Field(
        default_factory=list, description="数据状态：加载中/成功/失败/空数据/无网络"
    )
    disabled_style: str = Field(default="", description="禁用状态样式")
    status_field_color_icon: bool = Field(
        default=False, description="状态字段是否配颜色图标"
    )
    progress_states: List[str] = Field(
        default_factory=list, description="进度条三状态"
    )
    has_global_loading: bool = Field(default=False, description="是否有全局 Loading")
    has_empty_page: bool = Field(default=False, description="是否有空数据页面设计")


class ErrorHandlingSpec(BaseModel):
    """错误处理与提示规范"""

    has_global_catch: bool = Field(default=False, description="是否有全局错误捕获")
    error_classification: str = Field(default="", description="错误分类")
    error_copy_quality: str = Field(default="", description="错误文案质量")
    common_error_pre_check: bool = Field(
        default=False, description="是否有常见错误预判"
    )
    log_retention_days: str = Field(default="", description="日志保留天数")
    error_style: str = Field(default="", description="错误提示样式/色值")


class DataFormatSpec(BaseModel):
    """数据格式"""

    money_format: str = Field(default="", description="金额格式")
    date_format: str = Field(default="", description="日期格式")
    time_format: str = Field(default="", description="时间格式")
    empty_representation: str = Field(default="", description="无数据表示")
    status_color: str = Field(default="", description="状态色字段")
    string_length_limit: str = Field(default="", description="字符串长度限制")
    special_char_limit: str = Field(default="", description="特殊字符限制")
    sensitive_data_mask: List[str] = Field(
        default_factory=list, description="敏感数据脱敏字段"
    )


class PermissionSpec(BaseModel):
    """权限与数据可见性"""

    menu_permissions: List[str] = Field(
        default_factory=list, description="菜单权限点"
    )
    operation_permissions: str = Field(default="", description="操作权限粒度")
    data_permissions: List[str] = Field(
        default_factory=list, description="数据权限维度"
    )
    field_permissions: List[str] = Field(
        default_factory=list, description="字段权限：脱敏/隐藏/只读"
    )
    realtime_fetch: bool = Field(default=False, description="权限是否实时获取")
    has_change_log: bool = Field(default=False, description="是否有权限变更记录")
    requirements_preserved: bool = Field(
        default=False, description="是否前置标注权限需求"
    )


class FlowSpec(BaseModel):
    """业务流程完整性"""

    nodes: List[str] = Field(default_factory=list, description="流程节点")
    operations: List[str] = Field(
        default_factory=list,
        description="流程操作：暂存/撤回/重新申请/作废",
    )
    engine_params: str = Field(default="", description="流程引擎参数")
    all_params_marked: bool = Field(default=False, description="是否应传尽传")
    has_state_diagram: bool = Field(default=False, description="是否有状态流转图")
    uses_biz_id_index: bool = Field(default=False, description="是否业务 id 联合索引")


class PerformanceSpec(BaseModel):
    """性能与约束标注"""

    list_data_volume: str = Field(default="", description="列表数据量级")
    load_time_requirement: str = Field(default="", description="加载时间要求")
    time_range_limit: str = Field(default="", description="时间区间查询范围")
    file_size_limit: str = Field(default="", description="文件上传大小限制")
    avatar_size_limit: str = Field(default="", description="头像尺寸限制")
    string_length_limit: str = Field(default="", description="字符串长度限制")
    batch_op_limit: str = Field(default="", description="批量操作限制")
    cache_strategy: str = Field(default="", description="缓存策略")
    index_length_limit: str = Field(default="", description="字符串索引长度限制")


class SecuritySpec(BaseModel):
    """安全要求"""

    encryption: str = Field(default="", description="敏感数据加密")
    mask_fields: List[str] = Field(default_factory=list, description="敏感数据脱敏字段")
    password_plaintext: bool = Field(default=False, description="密码是否明文")
    special_char_limit: str = Field(default="", description="特殊字符限制")
    file_type_size_limit: str = Field(default="", description="文件类型与大小限制")
    search_param_filter: bool = Field(default=False, description="是否过滤搜索参数")
    has_mfa: bool = Field(default=False, description="是否多因素认证")
    token_expiry: str = Field(default="", description="接口 Token 过期时间")
    uses_https: bool = Field(default=False, description="是否使用 HTTPS")


class ComponentSource(BaseModel):
    """组件来源"""

    component_lib: str = Field(default="", description="组件库")
    icon_lib: str = Field(default="", description="图标库")
    chart_lib: str = Field(default="", description="图表库")
    drag_modal: str = Field(default="", description="拖拽弹窗")


class SpecItemWithConfidence(BaseModel):
    """规格值（带置信度与符合性）"""

    value: str = Field(default="", description="具体数值或观察值")
    confidence: str = Field(default="", description="精确 / 目测 / 无法判断")
    context: str = Field(default="", description="应用场景/位置")
    compliance: str = Field(
        default="", description="标准符合性：符合/不符合/未标注"
    )


class ComplianceSummary(BaseModel):
    """强规符合性总览"""

    total: str = Field(default="", description="强规项总数")
    compliant: str = Field(default="", description="符合项数")
    non_compliant: str = Field(default="", description="不符合项数")
    unmarked: str = Field(default="", description="未标注项数")
    overall: str = Field(default="", description="整体符合度")


class NonCompliantItem(BaseModel):
    """强规不符合项"""

    no: int = Field(default=0, description="序号")
    rule: str = Field(default="", description="强规项")
    dimension: str = Field(default="", description="维度")
    standard: str = Field(default="", description="标准要求")
    actual: str = Field(default="", description="实际值")
    diff: str = Field(default="", description="差异说明")
    location: str = Field(default="", description="涉及位置")
    risk: str = Field(default="", description="风险等级：高/中/低")
    fix: str = Field(default="", description="修复建议")


class UnmarkedItem(BaseModel):
    """未标注项"""

    no: int = Field(default=0, description="序号")
    rule: str = Field(default="", description="强规项")
    standard: str = Field(default="", description="标准要求")
    actual: str = Field(default="", description="实际值（未标注）")
    diff: str = Field(default="", description="差异说明")
    location: str = Field(default="", description="涉及位置")
    risk: str = Field(default="", description="风险等级：高/中/低")
    fix: str = Field(default="", description="修复建议")


class UnjudgeableSpec(BaseModel):
    """无法从原型判断的规格"""

    spec: str = Field(default="", description="规格项")
    reason: str = Field(default="", description="原因")


class PrototypeAnalysis(BaseModel):
    """原型图分析结果（顶层结构）"""

    page_base: PageBaseInfo = Field(default_factory=PageBaseInfo)
    layout_nav: LayoutNav = Field(default_factory=LayoutNav)
    visual: VisualSpec = Field(default_factory=VisualSpec)
    components: ComponentSpec = Field(default_factory=ComponentSpec)
    interaction: InteractionSpec = Field(default_factory=InteractionSpec)
    state: StateSpec = Field(default_factory=StateSpec)
    error_handling: ErrorHandlingSpec = Field(default_factory=ErrorHandlingSpec)
    data_format: DataFormatSpec = Field(default_factory=DataFormatSpec)
    permission: PermissionSpec = Field(default_factory=PermissionSpec)
    flow: FlowSpec = Field(default_factory=FlowSpec)
    performance: PerformanceSpec = Field(default_factory=PerformanceSpec)
    security: SecuritySpec = Field(default_factory=SecuritySpec)
    component_source: ComponentSource = Field(default_factory=ComponentSource)
    # 规格值提取（用于对比报告）：key 形如 "字体/正文字体"，value 含 value/confidence/context/compliance
    specs: dict[str, SpecItemWithConfidence] = Field(
        default_factory=dict,
        description="规格值，key 形如 '字体/正文字体'",
    )
    # 强规符合性总览
    compliance_summary: ComplianceSummary = Field(default_factory=ComplianceSummary)
    non_compliant_items: List[NonCompliantItem] = Field(
        default_factory=list, description="强规不符合项清单"
    )
    unmarked_items: List[UnmarkedItem] = Field(
        default_factory=list, description="未标注项清单"
    )
    unjudgeable: List[UnjudgeableSpec] = Field(
        default_factory=list, description="无法从原型判断的规格"
    )


__all__ = [
    "PageBaseInfo",
    "LayoutNav",
    "ColorSpec",
    "FontSpec",
    "SpacingComponentSize",
    "IconSpec",
    "VisualSpec",
    "ButtonSpec",
    "FieldComponentMap",
    "FormSpec",
    "TableSpec",
    "WeakDialog",
    "StrongDialog",
    "DialogSpec",
    "FilterSpec",
    "StatCardSpec",
    "ComponentSpec",
    "NavInteractionSpec",
    "DebounceSpec",
    "FilterInteractionSpec",
    "ListInteractionSpec",
    "FormInteractionSpec",
    "MultiQuerySpec",
    "ShortcutSpec",
    "InteractionSpec",
    "StateSpec",
    "ErrorHandlingSpec",
    "DataFormatSpec",
    "PermissionSpec",
    "FlowSpec",
    "PerformanceSpec",
    "SecuritySpec",
    "ComponentSource",
    "SpecItemWithConfidence",
    "ComplianceSummary",
    "NonCompliantItem",
    "UnmarkedItem",
    "UnjudgeableSpec",
    "PrototypeAnalysis",
]
