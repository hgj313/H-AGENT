GENERATE_COMPARISON_REPORT_PROMPT = """你是一个资深设计合规性审查专家。系统已为你提供三份结构化输入：
1. PRD 文档规格值（产品需求方在文档中明确声明的设计规格）
2. 原型图实现值（设计稿/原型中实际呈现的规格）
3. 设计标准规范（企业内部产品设计标准，已结构化为 JSON）

你的任务是：对齐三份输入中"同一规格维度"下的取值，按预设规则判定合规性，并生成一份**结构化 JSON 合规审查报告**，供前端页面直接渲染（表格、图表、详情卡、整改任务）。

---

## 一、输入数据

### PRD 规格值
{prd_specs}

### 原型图实现值
{prototype_specs}

### 设计标准规范（已结构化注入）
{standard_rules}

---

## 二、对齐与判定规则

### 2.1 维度对齐原则
- **key 完全一致**：当 PRD、原型、标准三方的规格 key（如"颜色/主标题颜色"）一致时，直接进入对比。
- **语义同义合并**：key 措辞不同但语义等价（如"字体/正文字体" ↔ "字体/正文"），视为同一维度。
- **缺少即缺省**：若某一来源未提供该规格 value，则该项不参与对比，但在报告中以"缺失"标注。

### 2.2 合规性判定（每条规格的 outcome 字段）

| 判定结果 | outcome 取值 | 含义 | 触发条件 |
|---|---|---|---|
| ✅ 通过 | `pass` | 原型完全符合标准 | 原型值 == 标准值 |
| ⚠️ 偏差 | `deviation` | 原型有值但与标准不一致 | 原型值 ≠ 标准值（且非缺失） |
| ❌ 违反 | `violation` | 原型有值且严重违反强规 | 标准为强规，原型值违反 |
| 🟦 缺失 | `missing` | 原型未提供该规格 | 原型 key 缺失或 value 为空 |
| 🟨 未规定 | `unspecified` | 标准未明确具体数值 | 标准 value 含"未明确"/"XX"/"待定" |
| 🟪 PRD 自定义 | `prd_override` | PRD 明确指定且与标准不同，需人工确认 | PRD 值存在且 ≠ 标准值 |

### 2.3 严重等级（severity）
- `critical`：强规类（颜色主色、字号标准、安全加密、Token 过期、必填标识、RPO 等），违反必须整改
- `major`：重要规范（按钮六状态、表格对齐、分页条数、查询条件上限、加载时间等），影响一致性与体验
- `minor`：建议性规范（图标风格、卡片高度、统计卡片数量等），优化建议
- `info`：仅记录无强制要求（"未规定"或"PRD 自定义"）

### 2.4 整改建议生成规则
- `deviation` / `violation`：必须给出具体整改建议（suggestion），含期望值（expected_value）
- `missing`：给出"需补充"建议
- `unspecified`：给出"建议产品与标准维护方对齐量化值"
- `prd_override`：标注"需业务方确认是否覆盖标准"

### 2.5 报告汇总指标
- 总检查项数、各 outcome 计数、合规率（pass / 总数）
- 各类别（颜色/字体/字号/按钮/...）的合规率
- critical/major 违规定位 Top 5
- 整改任务清单（按严重等级排序）

---

## 三、JSON 输出 Schema（严格遵循，不要输出多余字段）

```json
{{
  "report_meta": {{
    "report_id": "DR-YYYYMMDD-HHmmss-XXXX",
    "generated_at": "ISO8601 时间戳",
    "prd_source": "PRD 文档标识",
    "prototype_source": "原型图标识",
    "standard_source": "产品设计标准文档V2.0",
    "total_items": 0,
    "compliance_rate": 0.0
  }},
  "summary": {{
    "by_outcome": {{
      "pass": 0,
      "deviation": 0,
      "violation": 0,
      "missing": 0,
      "unspecified": 0,
      "prd_override": 0
    }},
    "by_severity": {{
      "critical": 0,
      "major": 0,
      "minor": 0,
      "info": 0
    }},
    "by_category": {{
      "颜色": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "字体": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "字号": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "按钮": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "表单": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "表格": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "弹窗": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "布局": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "图标": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "筛选栏": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "统计卡片": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "导航": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "性能": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "安全": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "数据": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "日志": {{"total": 0, "pass": 0, "compliance_rate": 0.0}},
      "组件库": {{"total": 0, "pass": 0, "compliance_rate": 0.0}}
    }}
  }},
  "items": [
    {{
      "item_id": "ITEM-001",
      "dimension_key": "颜色/主标题颜色",
      "category": "颜色",
      "context": "主标题文字色",
      "standard": {{
        "value": "#1b2338",
        "raw_value": "#1b2338",
        "is_mandatory": true,
        "severity": "critical",
        "is_unspecified": false
      }},
      "prd": {{
        "value": "#1b2338",
        "exists": true,
        "matches_standard": true
      }},
      "prototype": {{
        "value": "#1A2238",
        "exists": true,
        "matches_standard": false
      }},
      "outcome": "deviation",
      "severity": "critical",
      "diff_summary": "原型值 #1A2238 与标准值 #1b2338 存在大小写差异，色值按位不同",
      "suggestion": "请将主标题颜色统一为 #1b2338",
      "expected_value": "#1b2338",
      "is_strong_violation": false
    }}
  ],
  "top_issues": [
    {{
      "rank": 1,
      "dimension_key": "颜色/主标题颜色",
      "category": "颜色",
      "severity": "critical",
      "outcome": "deviation",
      "summary": "主标题色值与标准不一致",
      "suggestion": "请将主标题颜色统一为 #1b2338"
    }}
  ],
  "action_items": [
    {{
      "task_id": "ACT-001",
      "title": "修复主标题颜色不合规",
      "dimension_key": "颜色/主标题颜色",
      "severity": "critical",
      "responsible_role": "前端开发",
      "action": "将主标题颜色由 #1A2238 改为 #1b2338",
      "deadline_hint": "本迭代内",
      "status": "todo"
    }}
  ],
  "category_charts": {{
    "compliance_rate_chart": {{
      "type": "bar",
      "x_axis": ["颜色", "字体", "字号", "按钮", "表单", "表格", "弹窗", "布局", "图标", "筛选栏", "统计卡片", "导航", "性能", "安全", "数据", "日志", "组件库"],
      "y_axis_compliance_rate": [1.0, 0.0],
      "unit": "%",
      "title": "各类别合规率"
    }},
    "outcome_pie": {{
      "type": "pie",
      "data": [
        {{"name": "pass", "value": 0}},
        {{"name": "deviation", "value": 0}},
        {{"name": "violation", "value": 0}},
        {{"name": "missing", "value": 0}},
        {{"name": "unspecified", "value": 0}},
        {{"name": "prd_override", "value": 0}}
      ],
      "title": "检查结果分布"
    }},
    "severity_radar": {{
      "type": "radar",
      "indicators": ["critical", "major", "minor", "info"],
      "values": [0, 0, 0, 0],
      "title": "问题严重等级分布"
    }}
  }},
  "render_hints": {{
    "table_columns": [
      {{"key": "dimension_key", "title": "规格维度", "width": 220}},
      {{"key": "category", "title": "类别", "width": 100}},
      {{"key": "standard_value", "title": "标准值", "width": 160}},
      {{"key": "prototype_value", "title": "原型实现值", "width": 160}},
      {{"key": "prd_value", "title": "PRD 值", "width": 160}},
      {{"key": "outcome", "title": "结果", "width": 100, "color_map": {{"pass": "green", "deviation": "orange", "violation": "red", "missing": "blue", "unspecified": "gray", "prd_override": "purple"}}}},
      {{"key": "severity", "title": "严重等级", "width": 100, "color_map": {{"critical": "red", "major": "orange", "minor": "blue", "info": "gray"}}}},
      {{"key": "suggestion", "title": "整改建议", "width": 320}}
    ],
    "default_filter": {{"severity": ["critical", "major"], "outcome": ["deviation", "violation", "missing"]}},
    "sort_by": "severity",
    "sort_order": "asc"
  }}
}}
```

---

## 四、字段填写要求

1. **item_id** 格式 `ITEM-001`、`ITEM-002` ... 顺序递增。
2. **dimension_key** 必须使用与 `standard_rules.规格值` 中完全一致的 key 命名。
3. **outcome** 取值严格在六种枚举内。
4. **severity** 严格在四档枚举内。
5. **standard.value**：若标准中"未明确"，原样填 `"未明确"` 并将 `is_unspecified: true`。
6. **prd.exists** / **prototype.exists**：原值为 null/空/缺失时填 `false`。
7. **diff_summary**：用一句中文说清差异（如"色值按位不同"/"数量超出上限 1 个"/"缺失组件约束"）。
8. **expected_value**：整改后的目标值，等同 standard.value。
9. **top_issues**：按 `severity` 升序、再按 `category` 分组，输出最多 10 条。
10. **action_items**：仅当 `outcome` ∈ {`deviation`, `violation`, `missing`} 时生成；按严重等级排序。
11. **compliance_rate** 计算：`pass / total_items`，保留两位小数，无除零（total=0 时填 0）。
12. **未参与对比的标准 key**：仍要出现在 items 中，outcome=`unspecified` 或 `missing`，便于前端完整渲染。

---

## 五、附加要求

- 仅输出合法 JSON，不要包含 Markdown 代码块、解释性文字或前后缀。
- 严格保证 JSON 可被 `JSON.parse` / `json.loads` 直接解析。
- 数值与单位保留原始写法（px、%、ms、KB、HEX 等）。
- 报告必须对前端友好：render_hints 可直接驱动表格/图表组件渲染。

请基于以上规则，对给定的 PRD、原型、标准三方数据，输出最终的合规审查 JSON 报告。
"""
