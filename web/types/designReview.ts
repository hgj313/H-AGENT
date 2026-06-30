/**
 * 设计审查报告类型 - 严格对齐后端
 * agent/graphs/design_review/schemas/report_schema.py
 */

export type CheckOutcome =
  | "pass"
  | "deviation"
  | "violation"
  | "missing"
  | "unspecified"
  | "prd_override";

export type SeverityLevel = "critical" | "major" | "minor" | "info";

export interface ReportMeta {
  report_id: string;
  generated_at: string;
  prd_source: string;
  prototype_source: string;
  standard_source: string;
  total_items: number;
  compliance_rate: number;
}

export interface SummaryByOutcome {
  pass: number;
  deviation: number;
  violation: number;
  missing: number;
  unspecified: number;
  prd_override: number;
}

export interface SummaryBySeverity {
  critical: number;
  major: number;
  minor: number;
  info: number;
}

export interface CategoryStats {
  total: number;
  pass: number;
  compliance_rate: number;
}

export interface Summary {
  by_outcome: SummaryByOutcome;
  by_severity: SummaryBySeverity;
  by_category: Record<string, CategoryStats>;
}

export interface StandardValue {
  value: string;
  raw_value: string;
  is_mandatory: boolean;
  severity: string;
  is_unspecified: boolean;
}

export interface PrdValue {
  value: string;
  exists: boolean;
  matches_standard: boolean;
}

export interface PrototypeValue {
  value: string;
  exists: boolean;
  matches_standard: boolean;
}

export interface CheckItem {
  item_id: string;
  dimension_key: string;
  category: string;
  context: string;
  standard: StandardValue;
  prd: PrdValue;
  prototype: PrototypeValue;
  outcome: CheckOutcome;
  severity: SeverityLevel;
  diff_summary: string;
  suggestion: string;
  expected_value: string;
  is_strong_violation: boolean;
}

export interface TopIssue {
  rank: number;
  dimension_key: string;
  category: string;
  severity: SeverityLevel;
  outcome: CheckOutcome;
  summary: string;
  suggestion: string;
}

export type ActionStatus = "todo" | "in_progress" | "done";

export interface ActionItem {
  task_id: string;
  title: string;
  dimension_key: string;
  severity: SeverityLevel;
  responsible_role: string;
  action: string;
  deadline_hint: string;
  status: ActionStatus;
}

export interface BarChart {
  type: "bar";
  x_axis: string[];
  y_axis_compliance_rate: number[];
  unit: string;
  title: string;
}

export interface PieSlice {
  name: string;
  value: number;
}

export interface PieChart {
  type: "pie";
  data: PieSlice[];
  title: string;
}

export interface RadarChart {
  type: "radar";
  indicators: string[];
  values: number[];
  title: string;
}

export interface CategoryCharts {
  compliance_rate_chart: BarChart;
  outcome_pie: PieChart;
  severity_radar: RadarChart;
}

export interface DesignReviewReport {
  meta: ReportMeta;
  summary: Summary;
  items: CheckItem[];
  top_issues: TopIssue[];
  action_items: ActionItem[];
  charts: CategoryCharts;
}

// ── 设计审查任务配置 ─────────────────────────────────────────────────
export interface DesignReviewRequest {
  message: string;
  file_paths: string[];
  image_urls: string[];
  session_id?: string;
  stream: boolean;
}
