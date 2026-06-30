/**
 * 实时审查面板 - P4 完整实施
 *
 * 布局：
 *  ┌──────────────────────────────────────────────────────────┐
 *  │ Header: 会话标题 + 状态徽标 + 停止按钮 + 跳报告按钮      │
 *  ├────────────────────┬─────────────────────────────────────┤
 *  │ 节点状态条（横向）  │ 思考流（THINKING 事件累积）          │
 *  │ Tools 时间线       │ 报告预览（从 message(type=report)）  │
 *  └────────────────────┴─────────────────────────────────────┘
 *
 * 自动触发：进入页面后立即 run()；不阻塞首屏。
 */
"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/common/Button";
import { Card } from "@/components/common/Card";
import { Skeleton } from "@/components/common/Skeleton";
import { ROUTES } from "@/constants/routes";
import { apiRequest } from "@/api/apiClient";
import { useDesignReviewSession } from "@/hooks/useDesignReviewSession";
import { designReviewService } from "@/services/designReviewService";
import { cn, formatTime } from "@/lib/utils";

// 节点定义顺序（与 design_review_graph 保持一致）
const NODE_STAGES: Array<{ key: string; label: string }> = [
  { key: "start", label: "开始" },
  { key: "analyze_prd", label: "PRD 分析" },
  { key: "analyze_prototype", label: "原型分析" },
  { key: "retrieve_standard", label: "规范检索" },
  { key: "barrier", label: "决策" },
  { key: "generate_report", label: "生成报告" },
];

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  pending: { label: "空闲", cls: "bg-gray-100 text-gray-500" },
  running: { label: "审查中", cls: "bg-blue-100 text-blue-700 animate-pulse" },
  completed: { label: "已完成", cls: "bg-green-100 text-green-700" },
  error: { label: "失败", cls: "bg-red-100 text-red-700" },
};

export default function DesignReviewSessionPage() {
  const params = useParams<{ id: string }>();
  const sessionId = params?.id ?? "";
  const {
    status,
    thinkingLog,
    toolTimeline,
    nodeStates,
    reportPreview,
    reportId,
    durationMs,
    error,
    run,
    abort,
  } = useDesignReviewSession();

  // 注意：必须在 client mount 后再设时间，否则 SSR 与 hydration 的时间不一致会报错
  const [startedAt, setStartedAt] = useState<string | null>(null);
  useEffect(() => {
    setStartedAt(new Date().toISOString());
  }, []);
  const [sessionMeta, setSessionMeta] = useState<{
    session_title: string;
    prd_path: string;
    image_urls: string[];
  } | null>(null);

  // 拉取会话元数据（标题/PRD/原型）—— 仅用于 UI 展示
  // 注意：run body 不依赖此数据（后端从 session DB 读）
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiRequest<{
          session?: {
            session_title?: string;
            prd_path?: string;
            image_urls?: string[];
          };
        }>(
          `/api/v1/design-review/sessions/${encodeURIComponent(sessionId)}`,
        );
        if (!cancelled && data?.session) {
          setSessionMeta({
            session_title: data.session.session_title ?? "",
            prd_path: data.session.prd_path ?? "",
            image_urls: data.session.image_urls ?? [],
          });
        }
      } catch {
        /* 静默：元数据缺失不影响主流程 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // 进入页面自动触发
  // 注意：run body 只发 message；prd_path / image_urls 由后端从 session DB 读取
  // （createSession 时已持久化；不需要再次随 run 传递）
  useEffect(() => {
    if (!sessionId) return;
    // 等 sessionMeta 至少首轮返回后再 run，避免 race condition
    // （如果 sessionMeta 一直没拿到，run 也照样发 — 后端会读 session DB）
    run(sessionId, {
      message: "",
    });
    // 故意只跑一次（sessionId 不变就只触发一次；sessionMeta 仅用于 UI 展示）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const badge = STATUS_BADGE[status] ?? STATUS_BADGE.pending;
  const finalReportId =
    reportId ?? (status === "completed" ? sessionId : null);

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand-100 bg-white p-4">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold text-brand-500">
            {sessionMeta?.session_title ?? `审查会话 ${sessionId.slice(0, 8)}`}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <span
              className={cn(
                "rounded-full px-2 py-0.5",
                badge.cls,
              )}
            >
              {badge.label}
            </span>
            <span>· 起始 {startedAt ? formatTime(startedAt) : "--:--:--"}</span>
            {durationMs != null && <span>· 耗时 {durationMs}ms</span>}
            <span className="truncate">· {sessionId}</span>
          </div>
        </div>
        <div className="flex gap-2">
          {status === "running" && (
            <Button variant="danger" onClick={abort} size="sm">
              停止
            </Button>
          )}
          {(status === "completed" || finalReportId) && (
            <Link href={ROUTES.designReviewReport(finalReportId || sessionId)}>
              <Button size="sm">查看完整报告</Button>
            </Link>
          )}
          <Link href={ROUTES.designReview}>
            <Button variant="ghost" size="sm">
              返回配置
            </Button>
          </Link>
        </div>
      </header>

      {/* 节点状态条 */}
      <Card>
        <h2 className="mb-3 text-sm font-medium text-brand-500">节点状态</h2>
        <ol className="flex flex-wrap items-center gap-2">
          {NODE_STAGES.map((n) => {
            const state = nodeStates[n.key];
            const dotCls =
              state === "completed"
                ? "bg-green-500"
                : state === "running"
                  ? "bg-blue-500 animate-pulse"
                  : state === "error" || state === "failed"
                    ? "bg-red-500"
                    : "bg-gray-300";
            return (
              <li
                key={n.key}
                className="flex items-center gap-1.5 rounded-md border border-brand-50 bg-brand-50/30 px-2.5 py-1 text-xs text-gray-600"
              >
                <span className={cn("h-2 w-2 rounded-full", dotCls)} />
                {n.label}
                {state && state !== "completed" && (
                  <span className="ml-1 text-[10px] text-gray-400">
                    ({state})
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 工具时间线 */}
        <Card>
          <h2 className="mb-3 text-sm font-medium text-brand-500">
            工具调用时间线
          </h2>
          {toolTimeline.length === 0 && (
            <p className="text-xs text-gray-400">暂无工具调用</p>
          )}
          <ol className="space-y-2">
            {toolTimeline.map((t, i) => (
              <li
                key={`${t.tool_id ?? t.name}-${i}`}
                className="rounded-md border border-brand-50 bg-white p-2 text-xs"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-brand-500">{t.name}</span>
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px]",
                      t.result_status === "error"
                        ? "bg-red-50 text-red-600"
                        : t.result !== undefined
                          ? "bg-green-50 text-green-600"
                          : "bg-blue-50 text-blue-600",
                    )}
                  >
                    {t.result_status === "error"
                      ? "ERROR"
                      : t.result !== undefined
                        ? "OK"
                        : "调用中"}
                  </span>
                </div>
                {Object.keys(t.args || {}).length > 0 && (
                  <pre className="mt-1 overflow-x-auto rounded bg-brand-50/40 p-1.5 text-[10px] text-gray-500">
                    {JSON.stringify(t.args, null, 0)}
                  </pre>
                )}
                {t.result && (
                  <pre className="mt-1 max-h-32 overflow-auto rounded bg-gray-50 p-1.5 text-[10px] text-gray-600">
                    {t.result.slice(0, 500)}
                    {t.result.length > 500 ? "..." : ""}
                  </pre>
                )}
              </li>
            ))}
          </ol>
        </Card>

        {/* 思考流 */}
        <Card>
          <h2 className="mb-3 text-sm font-medium text-brand-500">思考流</h2>
          {thinkingLog.length === 0 && (
            <Skeleton variant="text" className="h-4 w-2/3" />
          )}
          <ol className="space-y-1.5 text-xs text-gray-600">
            {thinkingLog.map((t) => (
              <li
                key={t.sequence}
                className="flex items-start gap-2 border-l-2 border-brand-100 pl-2"
              >
                <span className="text-[10px] text-gray-400">
                  #{t.sequence}
                </span>
                <span>
                  <span className="font-medium text-brand-500">
                    [{t.stage || "stage"}]
                  </span>{" "}
                  {t.content}
                </span>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      {/* 报告预览 */}
      {reportPreview && (
        <Card>
          <h2 className="mb-3 text-sm font-medium text-brand-500">报告预览</h2>
          <ReportSummary report={reportPreview} />
          {finalReportId && (
            <div className="mt-4 flex justify-end">
              <Link href={ROUTES.designReviewReport(finalReportId)}>
                <Button size="sm">查看完整报告（含虚拟列表）</Button>
              </Link>
            </div>
          )}
        </Card>
      )}

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}

/** 报告摘要块（不渲染 items 列表，避免重复 — 报告页用 react-window 渲染） */
function ReportSummary({
  report,
}: {
  report: Partial<import("@/types/designReview").DesignReviewReport>;
}) {
  const meta = report.meta;
  const summary = report.summary;
  return (
    <div className="space-y-2 text-sm text-gray-700">
      {meta && (
        <p>
          <span className="text-gray-400">报告 ID：</span>
          {meta.report_id} ·{" "}
          <span className="text-gray-400">合规率：</span>
          <span className="font-medium text-brand-500">
            {((meta.compliance_rate ?? 0) * 100).toFixed(1)}%
          </span>
        </p>
      )}
      {summary && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {Object.entries(summary.by_outcome ?? {}).map(([k, v]) => (
            <div
              key={k}
              className="rounded-md border border-brand-50 bg-brand-50/30 px-3 py-2 text-xs"
            >
              <div className="text-gray-400">{k}</div>
              <div className="text-lg font-semibold text-brand-500">{v}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
