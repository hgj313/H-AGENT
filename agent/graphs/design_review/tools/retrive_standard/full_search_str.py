"""
全量检索文本库
================
基于产品设计标准文档，针对 analyze_prototype/prompts.py 中 15 个分析维度、
50+ 强规项，结构化生成检索 query 与对应标准条文。

每个检索单元包含：
- query：用于向量库召回的检索语句
- category：所属分析维度
- standard_clause：标准文档中的对应条款
- expected_match：期望召回的标准条文要点
- strong_rule：是否为强规项（True/False）
- threshold：相关度阈值建议
"""

FULL_SEARCH_STRATEGY = {
    # ============================================================
    # 一、页面基础信息
    # ============================================================
    "page_basic_info": {
        "page_name": {
            "query": "产品设计标准 页面名称 标题 命名规范 业务命名",
            "category": "页面基础信息",
            "standard_clause": "一、1.通用原则 - 1.1 风格一致性 / 1.2 交互一致性",
            "expected_match": "页面名称应与导航菜单、面包屑、标签页保持一致命名，遵循业务术语规范",
            "strong_rule": False,
            "threshold": 0.5
        },
        "page_type": {
            "query": "产品设计标准 页面类型 列表页 详情页 表单页 统计页 流程页 分类",
            "category": "页面基础信息",
            "standard_clause": "一、3.精度要求 - 3.1/3.2/3.3 低保真/中保真/高保真",
            "expected_match": "页面类型影响原型保真度与精度要求，列表/详情/表单/统计/流程页各有规范",
            "strong_rule": False,
            "threshold": 0.5
        },
        "fidelity_level": {
            "query": "产品设计标准 低保真 中保真 高保真 原型精度 线框图 高质量图像 真实交互",
            "category": "页面基础信息",
            "standard_clause": "一、3.精度要求 - 3.1 低保真 / 3.2 中保真 / 3.3 高保真",
            "expected_match": "低保真使用线框和占位符；中保真包含基本视觉元素与基础交互；高保真完整视觉+真实交互+状态变化",
            "strong_rule": False,
            "threshold": 0.6
        },
        "flow_page": {
            "query": "产品设计标准 流程引擎 流程页面 流程节点 审批流程 暂存 撤回 重新申请 作废 应传尽传",
            "category": "业务流程完整性",
            "standard_clause": "三、9.流程设计",
            "expected_match": "流程引擎应传尽传原则，流程支持暂存/撤回/重新申请/作废，参数按项目/角色/岗位/用户寻找",
            "strong_rule": True,
            "threshold": 0.7
        }
    },

    # ============================================================
    # 二、布局与导航
    # ============================================================
    "layout_and_navigation": {
        "overall_layout": {
            "query": "产品设计标准 整体布局 左右布局 上下布局 1366 768 最低适应分辨率",
            "category": "布局与导航",
            "standard_clause": "二、1.6 布局",
            "expected_match": "整体布局采用左右布局，最低适应分辨率 1366px × 768px",
            "strong_rule": True,
            "threshold": 0.8
        },
        "top_nav": {
            "query": "产品设计标准 顶部导航栏 一级导航 用户信息 全局设置 固定高度",
            "category": "布局与导航",
            "standard_clause": "二、1.6 布局 - 顶部导航栏",
            "expected_match": "顶部导航栏包含一级导航、用户信息、全局设置等基本信息，固定高度自适应",
            "strong_rule": True,
            "threshold": 0.7
        },
        "left_menu": {
            "query": "产品设计标准 左侧菜单栏 二级菜单 自适应 收缩展开 默认展开",
            "category": "布局与导航",
            "standard_clause": "二、1.6 布局 - 左侧菜单栏",
            "expected_match": "左侧菜单栏为二级菜单栏，宽度默认自适应，可收缩展开，默认展开",
            "strong_rule": True,
            "threshold": 0.7
        },
        "nav_level": {
            "query": "产品设计标准 导航层级 4级 标签页 面包屑 多余层级",
            "category": "布局与导航",
            "standard_clause": "二、2.1 信息架构和导航设计 - 导航层级",
            "expected_match": "导航层级不允许超过 4 级，多余层级可考虑页面内置标签页或面包屑导航（更推荐标签页）",
            "strong_rule": True,
            "threshold": 0.9
        },
        "menu_text": {
            "query": "产品设计标准 菜单文案 6个字符 长度限制 一致性",
            "category": "布局与导航",
            "standard_clause": "二、2.1 信息架构和导航设计 - 导航层级",
            "expected_match": "导航菜单文案遵循一致性、易读性原则，长度不允许超过 6 个字符",
            "strong_rule": True,
            "threshold": 0.8
        },
        "breadcrumb_or_tab": {
            "query": "产品设计标准 标签页 面包屑 页面切换 多余层级处理",
            "category": "布局与导航",
            "standard_clause": "二、2.1 信息架构和导航设计 - 导航层级",
            "expected_match": "多余层级可考虑页面内置标签页或面包屑导航，更推荐标签页",
            "strong_rule": False,
            "threshold": 0.6
        },
        "multi_tab_management": {
            "query": "产品设计标准 多Table标签 关闭左侧 关闭右侧 关闭其他 刷新当前 批量操作",
            "category": "快捷交互",
            "standard_clause": "二、2.8 快捷交互方式",
            "expected_match": "多页面 table 标签：提供关闭左侧、关闭右侧、关闭其他、刷新当前 table 页功能；批量操作快捷按钮",
            "strong_rule": True,
            "threshold": 0.7
        },
        "global_search": {
            "query": "产品设计标准 菜单全局搜索 全局检索 快捷入口",
            "category": "快捷入口",
            "standard_clause": "二、2.1 信息架构和导航设计 - 快捷入口",
            "expected_match": "提供菜单全局搜索功能；在首页提供用户常用功能的快捷入口",
            "strong_rule": False,
            "threshold": 0.6
        }
    },

    # ============================================================
    # 三、视觉规范 - 颜色
    # ============================================================
    "visual_color": {
        "global_color_count": {
            "query": "产品设计标准 全局颜色 3种 主色 辅助色 中性色 色系总数 颜色规范",
            "category": "颜色强规",
            "standard_clause": "二、1.1 颜色与字体 - 颜色规范",
            "expected_match": "全局颜色原则上不允许超过 3 种：主色系 + 辅助色 + 中性色",
            "strong_rule": True,
            "threshold": 0.9
        },
        "primary_color": {
            "query": "产品设计标准 主色 蓝色 默认版本 一键切换 自定义颜色 暗黑模式",
            "category": "颜色规范",
            "standard_clause": "二、1.1 颜色与字体 - 颜色规范",
            "expected_match": "主色系默认蓝色通用版本，支持一键更改主色为自定义颜色，支持白天/暗黑模式",
            "strong_rule": True,
            "threshold": 0.8
        },
        "secondary_color": {
            "query": "产品设计标准 辅助色 中性色 主色系 色值",
            "category": "颜色规范",
            "standard_clause": "二、1.1 颜色与字体 - 颜色规范",
            "expected_match": "辅助色与中性色（文字、背景等）配合主色使用，整体色系不超过 3 种",
            "strong_rule": False,
            "threshold": 0.6
        },
        "title_color": {
            "query": "产品设计标准 主标题 16px 加粗 #1b2338 一级导航 大模块 弹窗标题",
            "category": "字号样式",
            "standard_clause": "二、1.1 颜色与字体 - 字号及样式",
            "expected_match": "主标题 16px 加粗 #1b2338，使用范围：一级导航栏标题、大模块标题、弹窗标题、卡片正文",
            "strong_rule": True,
            "threshold": 0.9
        },
        "subtitle_color": {
            "query": "产品设计标准 次标题 14px 加粗 #1b2338 表格标题",
            "category": "字号样式",
            "standard_clause": "二、1.1 颜色与字体 - 字号及样式",
            "expected_match": "次标题 14px 加粗 #1b2338，表格标题",
            "strong_rule": True,
            "threshold": 0.9
        },
        "body_color": {
            "query": "产品设计标准 正文 14px 12px 常规 #1b2338 次级导航 表格内 下拉",
            "category": "字号样式",
            "standard_clause": "二、1.1 颜色与字体 - 字号及样式",
            "expected_match": "正文 14px 常规 #1b2338（次级导航标题、小标题、表格标题）；正文 12px 常规 #1b2338（表格内、下拉选择文字）",
            "strong_rule": True,
            "threshold": 0.9
        },
        "auxiliary_text": {
            "query": "产品设计标准 辅助文字 14px #b4b5bf 卡片标题 输入框提示",
            "category": "字号样式",
            "standard_clause": "二、1.1 颜色与字体 - 字号及样式",
            "expected_match": "辅助文字 14px 常规 #b4b5bf，卡片标题、输入框提示文字",
            "strong_rule": True,
            "threshold": 0.9
        },
        "disabled_text": {
            "query": "产品设计标准 失效文字 12px #c3cbd6 禁用 灰置",
            "category": "字号样式",
            "standard_clause": "二、1.1 颜色与字体 - 字号及样式",
            "expected_match": "失效文字 12px 常规 #c3cbd6，失效文字、禁用按钮",
            "strong_rule": True,
            "threshold": 0.9
        },
        "error_text": {
            "query": "产品设计标准 错误提示文字 14px #f5222d 错误样式",
            "category": "字号样式",
            "standard_clause": "二、1.1 颜色与字体 - 字号及样式",
            "expected_match": "错误提示文字 14px 常规 #f5222d，错误提示样式",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 三、视觉规范 - 字体
    # ============================================================
    "visual_font": {
        "cn_font": {
            "query": "产品设计标准 中文字体 微软雅黑 PingFang SC Windows Mac OS",
            "category": "字体规范",
            "standard_clause": "二、1.1 颜色与字体 - 字体规范",
            "expected_match": "中文字体：Windows 使用微软雅黑；Mac OS 使用 PingFang SC",
            "strong_rule": True,
            "threshold": 0.9
        },
        "en_font": {
            "query": "产品设计标准 英文字体 Arial PingFang SC Windows Mac",
            "category": "字体规范",
            "standard_clause": "二、1.1 颜色与字体 - 字体规范",
            "expected_match": "英文字体：Windows 使用 Arial；Mac OS 使用 PingFang SC",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 三、视觉规范 - 间距与组件尺寸
    # ============================================================
    "visual_size": {
        "card_height": {
            "query": "产品设计标准 统计卡片 高度 12px 70px 16px 90px 文字大小",
            "category": "组件尺寸",
            "standard_clause": "二、1.9 统计卡片",
            "expected_match": "12px 文字卡片建议高度 70px；16px 文字卡片建议高度 90px",
            "strong_rule": True,
            "threshold": 0.8
        },
        "avatar_size": {
            "query": "产品设计标准 头像尺寸 80px 80×80 压缩 资源限制",
            "category": "组件尺寸",
            "standard_clause": "三、2.页面查询 - 优化资源",
            "expected_match": "限制用户头像大小为 80px × 80px，超过增加压缩",
            "strong_rule": True,
            "threshold": 0.9
        },
        "button_size": {
            "query": "产品设计标准 按钮 size middle large small antdesign 按钮尺寸",
            "category": "按钮规范",
            "standard_clause": "二、1.2 按钮 - 基础规则",
            "expected_match": "按钮默认 size 遵循 antdesign 按钮尺寸 middle，需要设置为 large 或 small 的按钮需特殊说明",
            "strong_rule": True,
            "threshold": 0.9
        },
        "space_gap": {
            "query": "产品设计标准 space 组件 small 按钮间距 默认 size",
            "category": "按钮规范",
            "standard_clause": "二、1.2 按钮 - 基础规则",
            "expected_match": "按钮间距默认使用 space 组件，默认 size 为 small",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 三、视觉规范 - 图标
    # ============================================================
    "visual_icon": {
        "icon_library": {
            "query": "产品设计标准 图标库 antdesign 线框风格 双色图标 aliIcon",
            "category": "图标规范",
            "standard_clause": "二、1.7 图标",
            "expected_match": "图标库统一选用 antdesign 风格图标；菜单栏图标一般选用线框风格；单独出现的图标一般选用双色；额外图标使用 aliIcon 项目库",
            "strong_rule": True,
            "threshold": 0.8
        },
        "chart_library": {
            "query": "产品设计标准 图表库 ECharts AntV 统计图",
            "category": "组件来源",
            "standard_clause": "二、1.9 统计卡片",
            "expected_match": "图表选用 ECharts 或 AntV",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 四、组件规范 - 按钮
    # ============================================================
    "component_button": {
        "button_six_states": {
            "query": "产品设计标准 按钮六状态 正常 聚焦 悬停 激活 加载 禁用 状态设计",
            "category": "按钮强规",
            "standard_clause": "二、1.2 按钮 - 按钮交互六状态",
            "expected_match": "六状态：正常、聚焦（Tab/方向键访问，设计时不可忽略）、悬停（移动端不展示）、激活、加载（B 端强规）、禁用（灰置或透明）",
            "strong_rule": True,
            "threshold": 0.9
        },
        "strong_cta_color": {
            "query": "产品设计标准 强引导 按钮 主色 蓝色 从左到右 颜色规则",
            "category": "按钮强规",
            "standard_clause": "二、1.2 按钮 - 按钮颜色规则",
            "expected_match": "强烈要求用户操作的按钮使用蓝色（主题色），从左到右依次排列；其他按钮默认使用白色加边框按钮",
            "strong_rule": True,
            "threshold": 0.9
        },
        "list_small_button": {
            "query": "产品设计标准 列表小按钮 A标签 14px 6个字 表格内",
            "category": "按钮规范",
            "standard_clause": "二、1.2 按钮 - 基础规则",
            "expected_match": "列表里小按钮默认为 A 标签，大小同表格文字大小（默认为 14px），文字不得超过 6 个字",
            "strong_rule": True,
            "threshold": 0.9
        },
        "list_tabs": {
            "query": "产品设计标准 tabs 组件 切换列表 按钮",
            "category": "按钮规范",
            "standard_clause": "二、1.2 按钮 - 基础规则",
            "expected_match": "切换列表按钮默认使用 tabs 组件",
            "strong_rule": False,
            "threshold": 0.7
        },
        "loading_state": {
            "query": "产品设计标准 Loading 加载状态 B端 按钮 等待",
            "category": "按钮强规",
            "standard_clause": "二、1.2 按钮 - 按钮交互六状态",
            "expected_match": "加载状态：等待期间不可操作，B 端产品 Loading 状态特别重要",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 四、组件规范 - 表单
    # ============================================================
    "component_form": {
        "input_component_mapping": {
            "query": "产品设计标准 InputMoney InputNumber Input Textarea Wangedit 富文本 金额 数字 文本 组件对应",
            "category": "表单规范",
            "standard_clause": "二、1.3 表单样式 - 输入框类型与组件对应",
            "expected_match": "金额→InputMoney（默认小数点后 2 位）；数字→InputNumber；文本→Input；文本域→Textarea（字数显示+限制）；富文本→Wangedit",
            "strong_rule": True,
            "threshold": 0.9
        },
        "required_marker": {
            "query": "产品设计标准 必填项 红色 星号 标签 标识",
            "category": "表单强规",
            "standard_clause": "二、1.3 表单样式 - 输入框规则",
            "expected_match": "必填项：标签前加红色 * 号",
            "strong_rule": True,
            "threshold": 0.9
        },
        "label_alignment": {
            "query": "产品设计标准 表单标签 对齐 左对齐 右对齐 字符多",
            "category": "表单规范",
            "standard_clause": "二、1.3 表单样式 - 表单布局",
            "expected_match": "对齐方式：一般为左对齐；标签字符多时统一右对齐",
            "strong_rule": True,
            "threshold": 0.8
        },
        "fields_per_row": {
            "query": "产品设计标准 表单 单行 3-4个 字段 Item 上下格式 编辑样式",
            "category": "表单强规",
            "standard_clause": "二、1.3 表单样式 - 表单布局",
            "expected_match": "编辑样式：Form 组件 + Item 组件 + 上下格式 + 单行 3-4 个 + 最多 4 个；详情样式：ProDescriptions + 单行 3-4 个",
            "strong_rule": True,
            "threshold": 0.9
        },
        "char_limit": {
            "query": "产品设计标准 Textarea 字数显示 字数限制 富文本 操作栏",
            "category": "表单规范",
            "standard_clause": "二、1.3 表单样式 - 输入框类型与组件对应",
            "expected_match": "文本域需添加字数显示和可输入字数限制；富文本操作栏配置需在业务场景下明确",
            "strong_rule": True,
            "threshold": 0.8
        },
        "format_validation": {
            "query": "产品设计标准 邮箱 身份证 手机号 社会信用代码 银行卡号 格式校验 数据类型",
            "category": "表单规范",
            "standard_clause": "二、1.3 表单样式 - 格式校验字段",
            "expected_match": "需要明确提示输入格式：邮箱、身份证、手机号、社会信用代码、银行卡号",
            "strong_rule": True,
            "threshold": 0.8
        },
        "instant_submit_validation": {
            "query": "产品设计标准 即时验证 提交验证 错误提示 字段高亮",
            "category": "表单交互",
            "standard_clause": "二、2.6 表单处理",
            "expected_match": "即时验证 + 提交验证 + 错误字段高亮 + 成功提示（跳转/刷新）",
            "strong_rule": True,
            "threshold": 0.7
        },
        "exit_interaction": {
            "query": "产品设计标准 表单 退出交互 关闭 主页按钮",
            "category": "表单交互",
            "standard_clause": "二、2.6 表单处理",
            "expected_match": "考虑退出交互方式（如主页面的操作按钮因没有单独关闭按钮，需设计退出方式）",
            "strong_rule": True,
            "threshold": 0.7
        },
        "placeholder_disappear": {
            "query": "产品设计标准 提示词 输入框提示 业务场景 精准编写",
            "category": "表单规范",
            "standard_clause": "二、1.3 表单样式 - 输入框规则",
            "expected_match": "提示词需根据业务场景精准编写，输入信息后提示文字消失；初始值需手动删除",
            "strong_rule": True,
            "threshold": 0.7
        }
    },

    # ============================================================
    # 四、组件规范 - 表格
    # ============================================================
    "component_table": {
        "money_format": {
            "query": "产品设计标准 金额格式 ￥ 千分位 valueType moneyCent",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 数据规则",
            "expected_match": "金额格式统一使用 ￥ 符号（valueType: moneyCent），按千分位分割",
            "strong_rule": True,
            "threshold": 0.9
        },
        "empty_value": {
            "query": "产品设计标准 无数据 — 破折号 区别于0 表格",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 数据规则",
            "expected_match": "无数据：用 — 表示，区别于 0",
            "strong_rule": True,
            "threshold": 0.9
        },
        "status_color_icon": {
            "query": "产品设计标准 状态字段 颜色图标 区分 表格",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 数据规则",
            "expected_match": "状态字段添加颜色图标用于区分",
            "strong_rule": True,
            "threshold": 0.9
        },
        "column_alignment": {
            "query": "产品设计标准 表格对齐 金额右对齐 操作列右对齐 文字居中",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 表格对齐方式",
            "expected_match": "金额/操作列始终右对齐；文字内容默认居中对齐；金额/操作列标题和内容右对齐",
            "strong_rule": True,
            "threshold": 0.9
        },
        "column_count": {
            "query": "产品设计标准 表格列数 3-10列 横向滚动 固定列",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 表格列数",
            "expected_match": "默认展示列数 3-10 列；列数过多时优先固定重要列（编码、名称等），其余列横向滚动展示；横向滚动时需固定前面重要数据列和右侧操作列",
            "strong_rule": True,
            "threshold": 0.9
        },
        "header_title_length": {
            "query": "产品设计标准 表头标题 8个字 信息精简 字符数",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 表头标题",
            "expected_match": "每列表头标题字符最多 8 个，文字太多需做信息精简",
            "strong_rule": True,
            "threshold": 0.9
        },
        "action_button_length": {
            "query": "产品设计标准 操作列 6个字 按钮 字数",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 操作列",
            "expected_match": "每个按钮字数不超过 6 个字",
            "strong_rule": True,
            "threshold": 0.9
        },
        "horizontal_scroll_freeze": {
            "query": "产品设计标准 表格横向滚动 固定首列 固定操作列",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 表格列数",
            "expected_match": "横向滚动时需固定前面重要数据列和右侧操作列",
            "strong_rule": True,
            "threshold": 0.8
        },
        "vertical_scroll_freeze": {
            "query": "产品设计标准 表格竖向滚动 固定表头 固定页码 筛选栏",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 筛选栏和滚动条",
            "expected_match": "固定筛选栏和表头位置（表头固定，表格内容可滚动）；固定表格整体高度，不能出现外部滚动条；竖向滚动时需固定表头标题栏和页码",
            "strong_rule": True,
            "threshold": 0.9
        },
        "external_scrollbar": {
            "query": "产品设计标准 表格 外部滚动条 不允许 自适应高度",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 筛选栏和滚动条",
            "expected_match": "固定表格整体高度，不能出现外部滚动条",
            "strong_rule": True,
            "threshold": 0.9
        },
        "detail_inline_rows": {
            "query": "产品设计标准 详情页内嵌表格 15行 表格高度",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 筛选栏和滚动条",
            "expected_match": "详情页内嵌表格行数不能少于 15 行数据",
            "strong_rule": True,
            "threshold": 0.9
        },
        "ptable_component": {
            "query": "产品设计标准 Ptable 组件 small size 表格",
            "category": "组件来源",
            "standard_clause": "二、1.4 表格数据展示 - 表格标题栏和内容栏",
            "expected_match": "默认使用 Ptable 组件，size 为 small；默认第一列为序号",
            "strong_rule": True,
            "threshold": 0.9
        },
        "index_column": {
            "query": "产品设计标准 表格 序号列 第一列 默认",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 表格标题栏和内容栏",
            "expected_match": "默认第一列为序号",
            "strong_rule": True,
            "threshold": 0.9
        },
        "zebra_stripe": {
            "query": "产品设计标准 表格 斑马纹 系统报表 隔行 颜色",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 斑马纹",
            "expected_match": "系统报表页面隔行添加斑马纹，颜色和表头背景色一致",
            "strong_rule": True,
            "threshold": 0.9
        },
        "pagination": {
            "query": "产品设计标准 表格分页 20条 50条 100条 每页条数",
            "category": "表格强规",
            "standard_clause": "二、1.4 表格数据展示 - 分页栏",
            "expected_match": "默认 20 条/页；支持切换 50 条/页、100 条/页；超过 100 条需视具体业务场景灵活处理",
            "strong_rule": True,
            "threshold": 0.9
        },
        "sort_rule": {
            "query": "产品设计标准 列表 排序 默认排序 业务场景 字段",
            "category": "表格规范",
            "standard_clause": "二、1.4 表格数据展示 - 排序规则",
            "expected_match": "所有列表应明确默认排序方式；需要支持用户手动排序时，应明确是何字段、何种排序方式",
            "strong_rule": True,
            "threshold": 0.7
        },
        "progress_states": {
            "query": "产品设计标准 进度条 加载中 成功 失败 三种状态",
            "category": "组件规范",
            "standard_clause": "二、1.4 表格数据展示 - 进度条状态",
            "expected_match": "进度条三种状态：加载中、成功、失败",
            "strong_rule": True,
            "threshold": 0.9
        },
        "header_filter": {
            "query": "产品设计标准 表头筛选 默认不展示 固定第一行 置灰",
            "category": "表格强规",
            "standard_clause": "二、1.8 筛选栏 - 表头筛选规则",
            "expected_match": "默认不使用表头筛选进行页面数据查询；特定业务场景需要时表头筛选需固定在第一行；无法筛选字段需置灰",
            "strong_rule": True,
            "threshold": 0.8
        }
    },

    # ============================================================
    # 四、组件规范 - 弹窗
    # ============================================================
    "component_modal": {
        "toast": {
            "query": "产品设计标准 Toast 弱提示 3-5秒 自动消失 普通 成功 失败 警告",
            "category": "弹窗强规",
            "standard_clause": "二、1.5 弹窗 - 弱弹窗",
            "expected_match": "Toast 弱提示：普通信息/成功/失败/警告，3-5 秒自动消失",
            "strong_rule": True,
            "threshold": 0.9
        },
        "hover_popover": {
            "query": "产品设计标准 悬停弹窗 无遮罩 浮动 阴影 鼠标移过",
            "category": "弹窗强规",
            "standard_clause": "二、1.5 弹窗 - 弱弹窗",
            "expected_match": "悬停弹窗：提示说明、显示更多信息；鼠标移过立即消失；无遮罩层，浮动带阴影效果",
            "strong_rule": True,
            "threshold": 0.9
        },
        "toast_color": {
            "query": "产品设计标准 弱弹窗 颜色 error 红色 warning 黄色 success 绿色",
            "category": "弹窗强规",
            "standard_clause": "二、1.5 弹窗 - 弱弹窗类型颜色",
            "expected_match": "错误类→error 类型（红色）；警告类→warning 类型（黄色）；成功类→success 类型（绿色）",
            "strong_rule": True,
            "threshold": 0.9
        },
        "modal": {
            "query": "产品设计标准 强弹窗 必须交互 新页面 Modal ProModal",
            "category": "弹窗强规",
            "standard_clause": "二、1.5 弹窗 - 强弹窗",
            "expected_match": "必须对这个对话框进行操作后才能离开（如列表、详情、表单确认信息弹窗）。可理解为新页面",
            "strong_rule": True,
            "threshold": 0.9
        },
        "modal_mask": {
            "query": "产品设计标准 弹窗 遮罩层 Modal ProModal 点击遮罩关闭",
            "category": "弹窗强规",
            "standard_clause": "二、1.5 弹窗 - 弹窗组件与遮罩",
            "expected_match": "使用 antd 的 Modal 组件或 proAntd 的 ProModal；自带遮罩层；设计时需明确是否需要添加点击遮罩层关闭弹窗",
            "strong_rule": True,
            "threshold": 0.9
        },
        "modal_centering": {
            "query": "产品设计标准 弹窗 居中 水平 横向 30% 最小比例",
            "category": "弹窗强规",
            "standard_clause": "二、1.5 弹窗 - 弹窗移动和比例",
            "expected_match": "交互类弹窗默认水平和横向居中；最小比例不小于 30%",
            "strong_rule": True,
            "threshold": 0.9
        },
        "modal_drag": {
            "query": "产品设计标准 弹窗 拖拽 缩放 DragModal 边界 视口",
            "category": "弹窗强规",
            "standard_clause": "二、1.5 弹窗 - 弹窗移动和比例",
            "expected_match": "支持缩放和移动弹窗位置，弹窗边界不能超过浏览器视窗外边界；拖拽缩放弹窗可使用项目组件库的 DragModal 和 DragModalFrom 组件",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 四、组件规范 - 筛选栏
    # ============================================================
    "component_filter": {
        "default_display_fields": {
            "query": "产品设计标准 筛选栏 默认展示 3个 字段 隐藏 7个",
            "category": "筛选栏强规",
            "standard_clause": "二、1.8 筛选栏 - 页面查询规则",
            "expected_match": "默认展示单行 3 个筛选字段，超过字段隐藏（不超过 7 个查询条件）",
            "strong_rule": True,
            "threshold": 0.9
        },
        "more_query_modal": {
            "query": "产品设计标准 筛选栏 7个 更多查询 弹窗 单独设置",
            "category": "筛选栏强规",
            "standard_clause": "二、1.8 筛选栏 - 页面查询规则",
            "expected_match": "超过 7 个查询条件需单独设置更多查询弹窗",
            "strong_rule": True,
            "threshold": 0.9
        },
        "manual_query": {
            "query": "产品设计标准 筛选栏 手动更新 用户点击查询",
            "category": "筛选栏强规",
            "standard_clause": "二、1.8 筛选栏 - 页面查询规则",
            "expected_match": "查询方式：手动更新模式（需用户点击查询）",
            "strong_rule": True,
            "threshold": 0.9
        },
        "single_field_clear": {
            "query": "产品设计标准 筛选栏 单独清除 输入内容按钮",
            "category": "筛选栏强规",
            "standard_clause": "二、1.8 筛选栏 - 通用规则",
            "expected_match": "每个筛选栏需要独立设置清除输入内容按钮",
            "strong_rule": True,
            "threshold": 0.9
        },
        "fuzzy_or_exact": {
            "query": "产品设计标准 筛选栏 模糊查询 精确查询 类型标注",
            "category": "筛选栏强规",
            "standard_clause": "二、1.8 筛选栏 - 通用规则",
            "expected_match": "每个筛选字段需明确支持模糊查询还是精确查询",
            "strong_rule": True,
            "threshold": 0.9
        },
        "multi_select": {
            "query": "产品设计标准 筛选栏 多选 字段 设计时明确",
            "category": "筛选栏强规",
            "standard_clause": "二、1.8 筛选栏 - 通用规则",
            "expected_match": "需要支持多选的字段需在设计时明确",
            "strong_rule": True,
            "threshold": 0.8
        },
        "time_format": {
            "query": "产品设计标准 时间格式 00:00:00 23:59:59 时间戳 范围",
            "category": "筛选栏强规",
            "standard_clause": "二、1.8 筛选栏 - 页面查询规则",
            "expected_match": "日期格式默认 00:00:00-23:59:59 格式，前端需对时间范围做处理，转换时间戳时需保证一致性",
            "strong_rule": True,
            "threshold": 0.9
        },
        "global_query": {
            "query": "产品设计标准 顶部查询 全局数据查询 全局检索",
            "category": "筛选栏强规",
            "standard_clause": "二、2.3 筛选栏交互 - 全局检索",
            "expected_match": "所有页面顶部的查询功能均为全局数据查询",
            "strong_rule": True,
            "threshold": 0.8
        },
        "clear_filter": {
            "query": "产品设计标准 筛选栏 一键清除 清除所有筛选条件",
            "category": "筛选栏交互",
            "standard_clause": "二、2.3 筛选栏交互 - 清除筛选",
            "expected_match": "提供一键清除所有筛选条件的功能",
            "strong_rule": True,
            "threshold": 0.7
        },
        "default_value": {
            "query": "产品设计标准 筛选栏 默认值 时间区间 带出",
            "category": "筛选栏交互",
            "standard_clause": "二、2.3 筛选栏交互 - 默认值带出",
            "expected_match": "时间区间等重要筛选条件应显示默认值，如：2024.6.1-2024.7.1",
            "strong_rule": True,
            "threshold": 0.7
        },
        "trim_space": {
            "query": "产品设计标准 筛选栏 空格 首尾 文字 输入处理",
            "category": "筛选栏交互",
            "standard_clause": "二、2.3 筛选栏交互 - 空格处理",
            "expected_match": "去掉筛选栏输入时文字首尾多余的空格",
            "strong_rule": True,
            "threshold": 0.7
        },
        "filter_debounce": {
            "query": "产品设计标准 筛选栏 防抖 频繁使用 数据缓存",
            "category": "筛选栏交互",
            "standard_clause": "二、2.3 筛选栏交互 - 防抖处理 / 数据缓存",
            "expected_match": "对筛选操作进行防抖处理；对频繁使用的筛选数据进行缓存",
            "strong_rule": True,
            "threshold": 0.7
        }
    },

    # ============================================================
    # 四、组件规范 - 统计卡片
    # ============================================================
    "component_stat_card": {
        "card_count": {
            "query": "产品设计标准 统计卡片 偶数 8个 2行 数量",
            "category": "统计卡片强规",
            "standard_clause": "二、1.9 统计卡片",
            "expected_match": "卡片数量一般为偶数，单行不超过 8 个，最多不超过 2 行",
            "strong_rule": True,
            "threshold": 0.9
        },
        "card_layout": {
            "query": "产品设计标准 统计卡片 居中 数据内容 宽度 隐藏",
            "category": "统计卡片强规",
            "standard_clause": "二、1.9 统计卡片",
            "expected_match": "数据内容不超过卡片宽度，超过部分隐藏；卡片内容居中",
            "strong_rule": True,
            "threshold": 0.8
        },
        "interactive_shadow": {
            "query": "产品设计标准 统计卡片 可交互 选中 外阴影 特效",
            "category": "统计卡片强规",
            "standard_clause": "二、1.9 统计卡片",
            "expected_match": "可交互卡片需设置选中添加外阴影特效",
            "strong_rule": True,
            "threshold": 0.8
        }
    },

    # ============================================================
    # 五、交互规范 - 防抖
    # ============================================================
    "interaction_debounce_throttle": {
        "input_debounce": {
            "query": "产品设计标准 输入框 防抖 搜索 校验 触发频率",
            "category": "防抖强规",
            "standard_clause": "二、2.2 防抖/节流机制",
            "expected_match": "输入框内容变化：对用户输入进行防抖处理，避免每次输入都触发搜索或校验",
            "strong_rule": True,
            "threshold": 0.9
        },
        "button_debounce": {
            "query": "产品设计标准 按钮防抖 连续点击 loading 多次提交",
            "category": "防抖强规",
            "standard_clause": "二、2.2 防抖/节流机制",
            "expected_match": "按钮点击防抖：防止连续点击导致多次提交，可通过 loading 优化体验",
            "strong_rule": True,
            "threshold": 0.9
        },
        "resize_debounce": {
            "query": "产品设计标准 窗口调整 防抖 重绘 重排 resize",
            "category": "防抖强规",
            "standard_clause": "二、2.2 防抖/节流机制",
            "expected_match": "窗口调整防抖：减少重绘和重排频率",
            "strong_rule": True,
            "threshold": 0.8
        },
        "api_request_merge": {
            "query": "产品设计标准 API请求 防抖 合并请求 异步",
            "category": "防抖强规",
            "standard_clause": "二、2.2 防抖/节流机制",
            "expected_match": "API 请求合并：多个 API 请求同时发送时，使用防抖合并请求；异步请求防抖：确保异步请求不会过于频繁",
            "strong_rule": True,
            "threshold": 0.8
        },
        "abort_controller": {
            "query": "产品设计标准 多查询方式 并行处理 AbortController 取消前次 接口",
            "category": "交互强规",
            "standard_clause": "二、2.5 多查询方式并行处理",
            "expected_match": "对于单查询比较快、查询所有比较慢的接口，需考虑接口每次调用时取消之前调用（还未返回数据的相同接口）；利用 AbortController API 进行处理",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 五、交互规范 - 列表
    # ============================================================
    "interaction_list": {
        "hover_highlight": {
            "query": "产品设计标准 列表 悬停 高亮 鼠标",
            "category": "列表交互",
            "standard_clause": "二、2.4 列表交互",
            "expected_match": "列表项鼠标悬停时应有高亮效果",
            "strong_rule": True,
            "threshold": 0.8
        },
        "click_effect": {
            "query": "产品设计标准 列表 点击 选中 当前项",
            "category": "列表交互",
            "standard_clause": "二、2.4 列表交互",
            "expected_match": "点击应有点击效果，并明确当前选中的项",
            "strong_rule": True,
            "threshold": 0.7
        },
        "single_row_edit": {
            "query": "产品设计标准 列表 单行编辑 编辑按钮 保存 自动保存 多行",
            "category": "列表强规",
            "standard_clause": "二、2.4 列表交互 - 可编辑表格模式",
            "expected_match": "可编辑表格默认使用单行编辑模式；多行编辑不推荐，直接开放可编辑字段自动保存",
            "strong_rule": True,
            "threshold": 0.9
        },
        "checkbox_clear": {
            "query": "产品设计标准 列表 勾选框 提交后 清除",
            "category": "列表强规",
            "standard_clause": "二、2.4 列表交互",
            "expected_match": "列表勾选框：选中并执行下一步操作、提交后应清除原勾选项",
            "strong_rule": True,
            "threshold": 0.8
        },
        "list_copy": {
            "query": "产品设计标准 列表 复制数据 功能 字段值",
            "category": "列表强规",
            "standard_clause": "二、2.4 列表交互",
            "expected_match": "需增加列表数据的页面需要提供复制列表数据功能；复制字段值时不要增加首末额外空格",
            "strong_rule": True,
            "threshold": 0.8
        },
        "list_refresh": {
            "query": "产品设计标准 列表 数据刷新 详情页返回 数据变更",
            "category": "列表强规",
            "standard_clause": "二、2.4 列表交互",
            "expected_match": "列表数据刷新：从详情页发生数据变更后返回列表需更新该列表对应数据的值",
            "strong_rule": True,
            "threshold": 0.8
        }
    },

    # ============================================================
    # 五、交互规范 - 快捷
    # ============================================================
    "interaction_shortcut": {
        "detail_close": {
            "query": "产品设计标准 详情页 关闭 ESC键 点击外部 关闭按钮",
            "category": "快捷强规",
            "standard_clause": "二、2.8 快捷交互方式",
            "expected_match": "所有详情页面需支持点击页面外和 ESC 键关闭，关闭按钮需保留",
            "strong_rule": True,
            "threshold": 0.9
        },
        "entry_close": {
            "query": "产品设计标准 数据录入页 关闭 仅支持 关闭按钮 限制",
            "category": "快捷强规",
            "standard_clause": "二、2.8 快捷交互方式",
            "expected_match": "数据录入页关闭：仅支持点击关闭按钮关闭",
            "strong_rule": True,
            "threshold": 0.9
        },
        "batch_operation": {
            "query": "产品设计标准 批量操作 批量选择 编辑 删除 快捷按钮",
            "category": "快捷强规",
            "standard_clause": "二、2.8 快捷交互方式",
            "expected_match": "为批量选择、编辑、删除等操作提供快捷按钮",
            "strong_rule": True,
            "threshold": 0.8
        }
    },

    # ============================================================
    # 六、状态定义
    # ============================================================
    "state_definition": {
        "data_state": {
            "query": "产品设计标准 数据状态 加载中 成功 失败 空数据 无网络",
            "category": "状态定义",
            "standard_clause": "六、状态定义 - 数据状态",
            "expected_match": "数据状态：加载中 / 成功 / 失败 / 空数据 / 无网络",
            "strong_rule": True,
            "threshold": 0.8
        },
        "disabled_state": {
            "query": "产品设计标准 禁用状态 灰置 透明 不可操作 样式",
            "category": "状态定义",
            "standard_clause": "六、状态定义 - 禁用状态样式",
            "expected_match": "禁用状态样式：灰置显示或透明度，不可操作",
            "strong_rule": True,
            "threshold": 0.8
        }
    },

    # ============================================================
    # 七、错误处理与提示规范
    # ============================================================
    "error_handling": {
        "global_error_catch": {
            "query": "产品设计标准 全局错误捕获 异常 处理机制",
            "category": "错误处理强规",
            "standard_clause": "二、2.7 错误处理和提示 - 全局错误处理",
            "expected_match": "实现全局错误捕获机制，捕获未处理的异常并进行处理",
            "strong_rule": True,
            "threshold": 0.9
        },
        "error_text_quality": {
            "query": "产品设计标准 错误文案 系统出错了 严禁 乱码 代码段 模糊",
            "category": "错误处理强规",
            "standard_clause": "二、2.7 错误处理和提示 / 三、10.错误处理与日志",
            "expected_match": "系统严禁出现代码段、乱码、以及简单粗暴的系统出错了这类描述；交互类报错示例需展示无法找到具体用户的角色名称及解决方法",
            "strong_rule": True,
            "threshold": 0.9
        },
        "error_classification": {
            "query": "产品设计标准 错误分类 交互类 缺陷类 产品经理 开发人员 责任人",
            "category": "错误处理强规",
            "standard_clause": "二、2.7 错误处理和提示 - 错误分类 / 三、10.错误处理与日志",
            "expected_match": "交互类报错由产品经理负责（交互操作不符合设计要求导致报错）；缺陷类报错由开发人员负责（代码缺陷、模块交互逻辑冲突）",
            "strong_rule": True,
            "threshold": 0.8
        },
        "log_retention": {
            "query": "产品设计标准 系统运行日志 3天 保留策略 详细错误信息",
            "category": "日志规范",
            "standard_clause": "二、2.7 错误处理和提示 - 日志记录 / 三、10.错误处理与日志 - 日志记录",
            "expected_match": "将详细的错误信息记录到日志中；系统运行日志保留策略：根据模块产出日志大小及用户访问量设定，暂定标准为 3 天",
            "strong_rule": True,
            "threshold": 0.9
        },
        "common_error_anticipation": {
            "query": "产品设计标准 错误预判 常见错误 报错信息 初步设计",
            "category": "错误处理",
            "standard_clause": "二、2.7 错误处理和提示 - 全局错误处理",
            "expected_match": "产品设计环节应对常见错误进行预判及报错信息初步设计",
            "strong_rule": True,
            "threshold": 0.7
        }
    },

    # ============================================================
    # 八、数据格式
    # ============================================================
    "data_format": {
        "date_format": {
            "query": "产品设计标准 日期格式 时间格式 YYYY-MM-DD 时间戳",
            "category": "数据格式",
            "standard_clause": "八、数据格式",
            "expected_match": "日期格式：YYYY-MM-DD；时间格式：00:00:00-23:59:59",
            "strong_rule": True,
            "threshold": 0.7
        },
        "string_length": {
            "query": "产品设计标准 字符串长度 512字节 备注 文字限制",
            "category": "数据格式",
            "standard_clause": "三、3.数据存取 - 字符串长度限定",
            "expected_match": "备注说明等文字一般限制为 512 字节",
            "strong_rule": True,
            "threshold": 0.9
        },
        "special_char": {
            "query": "产品设计标准 特殊字符 电子签 文件名 字段名 限制",
            "category": "数据格式",
            "standard_clause": "三、3.数据存取 - 特殊字符限定",
            "expected_match": "电子签等场景限制文件名及字段名不可出现特殊字符；一般场景不添加特殊字符限制",
            "strong_rule": True,
            "threshold": 0.8
        },
        "sensitive_data_mask": {
            "query": "产品设计标准 敏感数据 脱敏 身份证 手机号 银行卡 财务 薪酬",
            "category": "安全强规",
            "standard_clause": "三、8.安全要求 - 敏感数据加密 / 数据脱敏",
            "expected_match": "PII（姓名、身份证号、地址、电话、邮箱、银行账户）；财务数据；商业机密；员工薪酬；数据脱敏对不需要显示给用户的敏感数据进行脱敏处理",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 九、权限与数据可见性
    # ============================================================
    "permission_and_visibility": {
        "org_permission": {
            "query": "产品设计标准 组织权限 集团 子公司 部门 项目 用户 层级 数据权限",
            "category": "权限强规",
            "standard_clause": "三、5.权限设计 - 核心原则",
            "expected_match": "组织权限强规：必须考虑全组织架构各层级的数据权限控制（集团→子公司→部门→项目/用户）",
            "strong_rule": True,
            "threshold": 0.9
        },
        "permission_dimension": {
            "query": "产品设计标准 权限维度 菜单权限 操作权限 数据权限 字段权限 不可手动枚举 接口",
            "category": "权限强规",
            "standard_clause": "三、5.权限设计 - 核心原则",
            "expected_match": "数据权限维度（指定公司、物料类型等）不可手动枚举，应根据相应数据接口实时获取",
            "strong_rule": True,
            "threshold": 0.9
        },
        "permission_requirement_pre": {
            "query": "产品设计标准 权限需求 需求设计 初步方案 菜单 操作 数据 字段",
            "category": "权限规范",
            "standard_clause": "三、5.权限设计 - 核心原则",
            "expected_match": "菜单权限、操作权限、数据权限、字段权限的需求应在需求设计阶段给出初步方案",
            "strong_rule": True,
            "threshold": 0.8
        },
        "permission_change_log": {
            "query": "产品设计标准 权限变更 角色 岗位 用户 关联关系 记录",
            "category": "权限规范",
            "standard_clause": "三、5.权限设计 - 核心原则",
            "expected_match": "实时记录角色的权限变更明细，以及角色和岗位及用户的关联关系变动",
            "strong_rule": True,
            "threshold": 0.7
        }
    },

    # ============================================================
    # 十、业务流程完整性
    # ============================================================
    "business_flow": {
        "flow_operation_support": {
            "query": "产品设计标准 流程 暂存 撤回 重新申请 作废 完整功能 审批流",
            "category": "流程强规",
            "standard_clause": "一、1.5 功能完整性",
            "expected_match": "业务流程应闭环，实现端到端的流程。审批流应支持暂存、撤回、重新申请、作废等完整功能",
            "strong_rule": True,
            "threshold": 0.9
        },
        "pass_all_required_params": {
            "query": "产品设计标准 流程引擎 应传尽传 项目 角色 岗位 用户 参数",
            "category": "流程强规",
            "standard_clause": "三、9.流程设计 - 应传尽传原则",
            "expected_match": "流程引擎底层所设计的寻找用户所需的参数（按项目/角色/岗位/用户名寻找），各模块在开发流程功能时传参原则为应传尽传；除非遇到特别明显的不适配场景",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 十一、性能与约束
    # ============================================================
    "performance_and_constraint": {
        "load_time_requirement": {
            "query": "产品设计标准 加载时间 3秒 10w 结构化数据 详情页 性能",
            "category": "性能强规",
            "standard_clause": "三、2.页面查询 - 加载时间要求 / 三、7.性能优化",
            "expected_match": "10w+ 结构化数据列表加载时间 ≤ 3 秒；详情页数据加载时间 ≤ 3 秒；常用数据查询（10 万条结构化数据）< 3 秒；常用数据保存操作 < 2 秒",
            "strong_rule": True,
            "threshold": 0.9
        },
        "time_range_limit": {
            "query": "产品设计标准 时间区间 6个月 7天 劳务打卡 查询范围",
            "category": "性能强规",
            "standard_clause": "三、2.页面查询 - 时间区间限定",
            "expected_match": "单次查询最长支持 6 个月；劳务打卡等庞大数据最多支持 7 天",
            "strong_rule": True,
            "threshold": 0.9
        },
        "data_cache": {
            "query": "产品设计标准 数据缓存 5分钟 更新 一致性 先更新数据库",
            "category": "性能强规",
            "standard_clause": "三、2.页面查询 - 缓存失效处理 / 三、7.性能优化 - 缓存策略",
            "expected_match": "数据变更时主动更新缓存；接近失效时自动延长缓存时间；缓存一致性：先更新数据库，再更新缓存；缓存数据每 5 分钟更新",
            "strong_rule": True,
            "threshold": 0.9
        },
        "file_size_limit": {
            "query": "产品设计标准 文件大小 限制 上传 不同类型",
            "category": "性能规范",
            "standard_clause": "三、3.数据存取 - 文件大小限制",
            "expected_match": "不同文件类型有不同上传大小限制",
            "strong_rule": True,
            "threshold": 0.7
        },
        "batch_operation": {
            "query": "产品设计标准 批量操作 1000条 批次 数据库 性能",
            "category": "性能强规",
            "standard_clause": "数据库设计要求 - 批量操作",
            "expected_match": "每批次操作不超过 1000 条记录",
            "strong_rule": True,
            "threshold": 0.9
        },
        "index_field_length": {
            "query": "产品设计标准 字符串索引 255字符 数据库 长度",
            "category": "性能强规",
            "standard_clause": "数据库设计要求 - 索引字段长度",
            "expected_match": "字符串索引字段长度不超过 255 字符",
            "strong_rule": True,
            "threshold": 0.9
        }
    },

    # ============================================================
    # 十二、安全要求
    # ============================================================
    "security": {
        "sensitive_data_encryption": {
            "query": "产品设计标准 敏感数据加密 AES-256 数据传输 存储 PII",
            "category": "安全强规",
            "standard_clause": "三、8.安全要求 - 敏感数据加密",
            "expected_match": "数据传传输和存储过程使用加密手段（如 AES-256）。常见需加密的数据：PII、财务数据、商业机密数据、员工薪酬福利、用户密码",
            "strong_rule": True,
            "threshold": 0.9
        },
        "password_not_plain": {
            "query": "产品设计标准 密码 明文 浏览器控制台 不允许展示",
            "category": "安全强规",
            "standard_clause": "三、8.安全要求 - 敏感数据加密",
            "expected_match": "用户密码：浏览器控制台中用户的登录密码不允许明文展示",
            "strong_rule": True,
            "threshold": 0.9
        },
        "mfa": {
            "query": "产品设计标准 多因素认证 用户身份验证 访问控制",
            "category": "安全强规",
            "standard_clause": "三、8.安全要求 - 其他安全要求",
            "expected_match": "访问控制：增加用户身份验证的多因素认证",
            "strong_rule": True,
            "threshold": 0.8
        },
        "sql_injection": {
            "query": "产品设计标准 SQL注入 搜索参数 验证 过滤 用户输入",
            "category": "安全强规",
            "standard_clause": "三、8.安全要求 - 其他安全要求",
            "expected_match": "搜索参数验证：对用户输入的筛选条件进行严格输入验证和过滤，防止 SQL 注入",
            "strong_rule": True,
            "threshold": 0.9
        },
        "api_token": {
            "query": "产品设计标准 接口安全认证 token 5分钟 过期 外部调用",
            "category": "安全强规",
            "standard_clause": "三、6.数据接口 - 接口安全认证",
            "expected_match": "外部调用添加接口安全认证，如 5 分钟过期的 token 校验",
            "strong_rule": True,
            "threshold": 0.9
        },
        "https_protocol": {
            "query": "产品设计标准 HTTPS 安全协议 传输 加密",
            "category": "安全强规",
            "standard_clause": "三、6.数据接口 - 安全性",
            "expected_match": "采用 HTTPS 等安全协议传输",
            "strong_rule": True,
            "threshold": 0.8
        },
        "data_backup": {
            "query": "产品设计标准 数据备份 关键数据 每天定期 快速恢复",
            "category": "安全强规",
            "standard_clause": "三、8.安全要求 - 其他安全要求 / 三、11.数据备份",
            "expected_match": "每天定期备份关键数据，确保数据丢失后可快速恢复；数据快照保存时间 7 天；Binlog 日志文件备份保留时间 7 天；系统级别故障 RPO < 24 小时",
            "strong_rule": True,
            "threshold": 0.7
        }
    },

    # ============================================================
    # 十三、组件来源
    # ============================================================
    "component_source": {
        "ant_design": {
            "query": "产品设计标准 AntDesign 组件库 antd ProComponents proAntd",
            "category": "组件来源",
            "standard_clause": "一、4.交互范式 / 二、1 前端视觉规范",
            "expected_match": "产品在设计原型时尽量使用 AntDesign 组件库绘制对应原型图；前端视觉规范以 AntDesign 为主；强弹窗使用 antd Modal 或 proAntd ProModal",
            "strong_rule": True,
            "threshold": 0.9
        }
    }
}


# ============================================================
# 检索策略生成器
# ============================================================
def generate_search_queries(include_weak: bool = False) -> list:
    """
    生成全量检索 query 列表。

    Args:
        include_weak: 是否包含非强规项（默认 False，仅强规项）

    Returns:
        检索项列表，每项包含 query/category/strong_rule 等字段
    """
    queries = []
    for dimension, items in FULL_SEARCH_STRATEGY.items():
        for name, item in items.items():
            if not include_weak and not item.get("strong_rule", False):
                continue
            queries.append({
                "dimension": dimension,
                "item_name": name,
                "query": item["query"],
                "category": item["category"],
                "standard_clause": item["standard_clause"],
                "expected_match": item["expected_match"],
                "strong_rule": item.get("strong_rule", False),
                "threshold": item.get("threshold", 0.7)
            })
    return queries


def get_strong_rule_queries() -> list:
    """获取所有强规项检索 query"""
    return generate_search_queries(include_weak=False)


def get_all_queries() -> list:
    """获取全量检索 query（含非强规项）"""
    return generate_search_queries(include_weak=True)


def get_queries_by_dimension(dimension: str) -> list:
    """按维度获取检索 query"""
    items = FULL_SEARCH_STRATEGY.get(dimension, {})
    return [
        {
            "item_name": name,
            "query": item["query"],
            "category": item["category"],
            "standard_clause": item["standard_clause"],
            "expected_match": item["expected_match"],
            "strong_rule": item.get("strong_rule", False),
            "threshold": item.get("threshold", 0.7)
        }
        for name, item in items.items()
    ]


# ============================================================
# 统计信息
# ============================================================
def get_statistics() -> dict:
    """获取检索库统计信息"""
    total = 0
    strong = 0
    by_dimension = {}
    for dimension, items in FULL_SEARCH_STRATEGY.items():
        dim_total = len(items)
        dim_strong = sum(1 for it in items.values() if it.get("strong_rule", False))
        by_dimension[dimension] = {
            "total": dim_total,
            "strong_rule": dim_strong
        }
        total += dim_total
        strong += dim_strong
    return {
        "total_queries": total,
        "strong_rule_queries": strong,
        "weak_rule_queries": total - strong,
        "by_dimension": by_dimension
    }


if __name__ == "__main__":
    stats = get_statistics()
    print("=" * 60)
    print("标准文档检索库统计")
    print("=" * 60)
    print(f"总检索项：{stats['total_queries']}")
    print(f"强规项：{stats['strong_rule_queries']}")
    print(f"弱规项：{stats['weak_rule_queries']}")
    print()
    print("按维度分布：")
    for dim, info in stats["by_dimension"].items():
        print(f"  {dim}: 总 {info['total']} / 强规 {info['strong_rule']}")

    print()
    print("=" * 60)
    print("强规项检索示例（前 5 条）")
    print("=" * 60)
    for q in get_strong_rule_queries()[:5]:
        print(f"\n[维度] {q['dimension']} / [项] {q['item_name']}")
        print(f"[Query] {q['query']}")
        print(f"[条款] {q['standard_clause']}")
        print(f"[阈值] {q['threshold']}")
