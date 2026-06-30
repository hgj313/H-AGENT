/**
 * 报告查看页 - P4 完整实施
 *
 * 行为：
 *  - 路径参数 id 可能是 report_id（DR-…）或 dr_session_id
 *  - 先按 report_id 拉；失败则按 session 拉最新
 *  - items 列表用 react-window 虚拟列表（>100 条时）
 *  - 顶部展示 meta / summary / charts 摘要
 *  - top_issues / action_items 块直接渲染
 *  - 返回按钮跳实时面板；再返回主配置
 */
"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { FixedSizeList as VirtualList } from "react-window";
import { Button } from "@/components/common/Button";
import { Card } from "@/components/common/Card";
import { Skeleton } from "@/components/common/Skeleton";
import { ROUTES } from "@/constants/routes";
import { apiRequest, ApiError } from "@/api/apiClient";
import type { DesignReviewReport, CheckItem } from "@/types/designReview";
import { cn, formatTime } from "@/lib/utils";

const SEVERITY_CLS: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  major: "bg-orange-100 text-orange-700",
  minor: "bg-yellow-100 text-yellow-700",
  info: "bg-blue-100 text-blue-700",
};

const OUTCOME_CLS: Record<string, string> = {
  pass: "bg-green-100 text-green-700",
  deviation: "bg-orange-100 text-orange-700",
  violation: "bg-red-100 text-red-700",
  missing: "bg-gray-100 text-gray-600",
  unspecified: "bg-gray-100 text-gray-500",
  prd_override: "bg-blue-100 text-blue-700",
};

interface ReportResponse {
  success: boolean;
  report?: {
    report_id: string;
    dr_session_id: string;
    report_data: DesignReviewReport;
    status: string;
    duration_ms: number;
    created_at: number;
  };
}

export default function DesignReviewReportPage() {
  const params = useParams<{ id: string }>();
  const rawId = params?.id ?? "";
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<DesignReviewReport | null>(null);
  const [meta2, setMeta2] = useState<{
    report_id: string;
    dr_session_id: string;
    status: string;
    duration_ms: number;
    created_at: number;
  } | null>(null);

  useEffect(() => {
    if (!rawId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        // 先按 report_id 试；失败则按 dr_session_id
        const isReportId = rawId.startsWith("DR-");
        const primary = isReportId
          ? `/api/v1/design-review/reports/${encodeURIComponent(rawId)}`
          : `/api/v1/design-review/sessions/${encodeURIComponent(rawId)}/report`;
        let data: ReportResponse;
        try {
          data = await apiRequest<ReportResponse>(primary);
        } catch (e) {
          if (isReportId) throw e;
          // fallback：当作 report_id 再试
          try {
            data = await apiRequest<ReportResponse>(
              `/api/v1/design-review/reports/${encodeURIComponent(rawId)}`,
            );
          } catch {
            throw e;  // 抛原始的 session 错误
          }
        }
        if (cancelled) return;
        if (data?.report) {
          setReport(data.report.report_data);
          setMeta2({
            report_id: data.report.report_id,
            dr_session_id: data.report.dr_session_id,
            status: data.report.status,
            duration_ms: data.report.duration_ms,
            created_at: data.report.created_at,
          });
        } else {
          throw new Error("报告数据为空");
        }
      } catch (e) {
        if (!cancelled) {
          const msg = e instanceof ApiError
            ? `${e.message} (HTTP ${e.status})`
            : (e as Error).message;
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [rawId]);

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        <Skeleton variant="text" className="h-8 w-1/3" />
        <Skeleton variant="rect" className="h-32" />
        <Skeleton variant="rect" className="h-64" />
      </div>
    );
  }
  if (error || !report) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          报告加载失败：{error ?? "数据为空"}
        </div>
        <Link href={ROUTES.designReview}>
          <Button variant="ghost">返回任务配置</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <ReportHeader meta2={meta2} report={report} />

      <SummarySection report={report} />

      {report.top_issues?.length > 0 && (
        <Card>
          <h2 className="mb-3 text-sm font-medium text-brand-500">
            Top Issues
          </h2>
          <ol className="space-y-2">
            {report.top_issues.map((t) => (
              <li
                key={t.rank}
                className="rounded-md border border-brand-50 bg-white p-3 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="rounded bg-brand-500 px-1.5 py-0.5 text-xs text-white">
                    #{t.rank}
                  </span>
                  <span className="font-medium text-brand-500">
                    {t.dimension_key}
                  </span>
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px]",
                      SEVERITY_CLS[t.severity] ?? "bg-gray-100",
                    )}
                  >
                    {t.severity}
                  </span>
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px]",
                      OUTCOME_CLS[t.outcome] ?? "bg-gray-100",
                    )}
                  >
                    {t.outcome}
                  </span>
                </div>
                <p className="mt-1 text-gray-700">{t.summary}</p>
                {t.suggestion && (
                  <p className="mt-1 text-xs text-gray-500">
                    💡 {t.suggestion}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </Card>
      )}

      <CheckItemsList items={report.items ?? []} />

      {report.action_items?.length > 0 && (
        <Card>
          <h2 className="mb-3 text-sm font-medium text-brand-500">
            Action Items
          </h2>
          <ul className="divide-y divide-brand-50">
            {report.action_items.map((a) => (
              <li
                key={a.task_id}
                className="flex items-start justify-between gap-3 py-2 text-sm"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-brand-500">
                      {a.title}
                    </span>
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px]",
                        SEVERITY_CLS[a.severity] ?? "bg-gray-100",
                      )}
                    >
                      {a.severity}
                    </span>
                    {a.responsible_role && (
                      <span className="text-[10px] text-gray-500">
                        @{a.responsible_role}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-gray-600">{a.action}</p>
                  {a.deadline_hint && (
                    <p className="mt-0.5 text-[10px] text-gray-400">
                      ⏰ {a.deadline_hint}
                    </p>
                  )}
                </div>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px]",
                    a.status === "done"
                      ? "bg-green-100 text-green-700"
                      : a.status === "in_progress"
                        ? "bg-blue-100 text-blue-700"
                        : "bg-gray-100 text-gray-500",
                  )}
                >
                  {a.status}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="flex justify-between">
        <Link
          href={meta2 ? ROUTES.designReviewSession(meta2.dr_session_id) : ROUTES.designReview}
        >
          <Button variant="secondary">返回实时面板</Button>
        </Link>
        <Link href={ROUTES.designReview}>
          <Button variant="ghost">返回任务配置</Button>
        </Link>
      </div>
    </div>
  );
}

function ReportHeader({
  meta2,
  report,
}: {
  meta2: {
    report_id: string;
    dr_session_id: string;
    status: string;
    duration_ms: number;
    created_at: number;
  } | null;
  report: DesignReviewReport;
}) {
  return (
    <header className="rounded-lg border border-brand-100 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-semibold text-brand-500">
            设计审查报告
          </h1>
          <p className="mt-1 break-all text-xs text-gray-400">
            {meta2?.report_id ?? report.meta?.report_id}
          </p>
          <p className="mt-0.5 text-xs text-gray-500">
            生成于 {formatTime(new Date((meta2?.created_at ?? 0) * 1000).toISOString())}
            {meta2?.duration_ms ? ` · 耗时 ${meta2.duration_ms}ms` : ""} · 状态{" "}
            <span className="font-medium">{meta2?.status ?? "completed"}</span>
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-gray-400">合规率</div>
          <div className="text-3xl font-semibold text-brand-500">
            {((report.meta?.compliance_rate ?? 0) * 100).toFixed(1)}%
          </div>
          <div className="text-[10px] text-gray-400">
            共 {report.meta?.total_items ?? report.items?.length ?? 0} 项
          </div>
        </div>
      </div>
    </header>
  );
}

function SummarySection({ report }: { report: DesignReviewReport }) {
  const s = report.summary;
  if (!s) return null;
  return (
    <Card>
      <h2 className="mb-3 text-sm font-medium text-brand-500">汇总</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Object.entries(s.by_outcome ?? {}).map(([k, v]) => (
          <div
            key={`o-${k}`}
            className={cn(
              "rounded-md border border-brand-50 px-3 py-2 text-center",
              OUTCOME_CLS[k] ?? "bg-brand-50/30",
            )}
          >
            <div className="text-[10px] uppercase opacity-70">{k}</div>
            <div className="text-2xl font-semibold">{v}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Object.entries(s.by_severity ?? {}).map(([k, v]) => (
          <div
            key={`s-${k}`}
            className={cn(
              "rounded-md border border-brand-50 px-3 py-2 text-center",
              SEVERITY_CLS[k] ?? "bg-brand-50/30",
            )}
          >
            <div className="text-[10px] uppercase opacity-70">{k}</div>
            <div className="text-2xl font-semibold">{v}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** CheckItem 行（虚拟列表单行） */
function CheckItemRow({
  index,
  style,
  data,
}: {
  index: number;
  style: React.CSSProperties;
  data: { items: CheckItem[] };
}) {
  const item = data.items[index];
  if (!item) return null;
  return (
    <div
      style={style}
      className={cn(
        "border-b border-brand-50 px-3 py-2 text-xs",
        item.outcome === "violation"
          ? "bg-red-50/50"
          : item.outcome === "deviation"
            ? "bg-orange-50/40"
            : "bg-white",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-brand-500">
          #{index + 1} {item.dimension_key}
        </span>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px]",
            SEVERITY_CLS[item.severity] ?? "bg-gray-100",
          )}
        >
          {item.severity}
        </span>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px]",
            OUTCOME_CLS[item.outcome] ?? "bg-gray-100",
          )}
        >
          {item.outcome}
        </span>
        <span className="text-[10px] text-gray-400">{item.category}</span>
      </div>
      <p className="mt-0.5 line-clamp-2 text-gray-600">
        {item.context || item.diff_summary}
      </p>
      {item.suggestion && (
        <p className="mt-0.5 truncate text-[10px] text-gray-400">
          💡 {item.suggestion}
        </p>
      )}
    </div>
  );
}

function CheckItemsList({ items }: { items: CheckItem[] }) {
  const USE_VIRTUAL = items.length > 100;
  const ROW_H = 72;
  const MAX_H = 480;
  return (
    <Card>
      <h2 className="mb-3 text-sm font-medium text-brand-500">
        Check Items ({items.length})
      </h2>
      {items.length === 0 ? (
        <p className="text-xs text-gray-400">暂无 Check Item</p>
      ) : USE_VIRTUAL ? (
        <VirtualList
          height={MAX_H}
          itemCount={items.length}
          itemSize={ROW_H}
          width="100%"
          itemData={{ items }}
        >
          {CheckItemRow}
        </VirtualList>
      ) : (
        <div className="divide-y divide-brand-50">
          {items.map((it, i) => (
            <div
              key={it.item_id}
              className={cn(
                "px-3 py-2 text-xs",
                it.outcome === "violation"
                  ? "bg-red-50/50"
                  : it.outcome === "deviation"
                    ? "bg-orange-50/40"
                    : "bg-white",
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium text-brand-500">
                  #{i + 1} {it.dimension_key}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px]",
                    SEVERITY_CLS[it.severity] ?? "bg-gray-100",
                  )}
                >
                  {it.severity}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px]",
                    OUTCOME_CLS[it.outcome] ?? "bg-gray-100",
                  )}
                >
                  {it.outcome}
                </span>
                <span className="text-[10px] text-gray-400">
                  {it.category}
                </span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-gray-600">
                {it.context || it.diff_summary}
              </p>
              {it.suggestion && (
                <p className="mt-0.5 truncate text-[10px] text-gray-400">
                  💡 {it.suggestion}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
