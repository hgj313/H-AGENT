/**
 * useDesignReviewSession - 设计审查会话 hook
 *
 * 单一职责：管理一个审查会话的实时流式生命周期。
 * 不做：
 *  - 不渲染 UI（presentation 由组件负责）
 *  - 不做报告后处理（交给 ReportRenderer）
 *
 * 状态：
 *  - status: pending | running | completed | error
 *  - thinkingLog: 累积的 THINKING 事件
 *  - toolTimeline: 累积的 TOOL_CALL / TOOL_RESULT
 *  - nodeStates: 节点当前状态映射
 *  - reportPreview: 嵌在 message(type=report) 中的部分报告
 *  - reportId: DONE 事件中的 report_id
 */

"use client";

import { useCallback, useRef, useState } from "react";
import { designReviewService } from "@/services/designReviewService";
import type { DesignReviewRequest, DesignReviewReport } from "@/types/designReview";
import type {
  MessageEventData,
  NodeUpdateEventData,
  StreamEvent,
  ToolCallEventData,
  ToolResultEventData,
} from "@/types/chat";

export type DesignReviewStatus = "pending" | "running" | "completed" | "error";

export interface ThinkingEntry {
  stage: string;
  content?: string;
  sequence: number;
  timestamp: string;
}

export interface ToolEntry {
  name: string;
  args: Record<string, unknown>;
  tool_id?: string;
  result?: string;
  result_status?: "completed" | "error";
  sequence: number;
  timestamp: string;
}

export interface UseDesignReviewSessionResult {
  status: DesignReviewStatus;
  thinkingLog: ThinkingEntry[];
  toolTimeline: ToolEntry[];
  nodeStates: Record<string, NodeUpdateEventData["status"]>;
  reportPreview: Partial<DesignReviewReport> | null;
  reportId: string | null;
  durationMs: number | null;
  error: string | null;
  run: (sessionId: string, req: Omit<DesignReviewRequest, "stream" | "session_id">) => Promise<void>;
  abort: () => void;
  reset: () => void;
}

export function useDesignReviewSession(): UseDesignReviewSessionResult {
  const [status, setStatus] = useState<DesignReviewStatus>("pending");
  const [thinkingLog, setThinkingLog] = useState<ThinkingEntry[]>([]);
  const [toolTimeline, setToolTimeline] = useState<ToolEntry[]>([]);
  const [nodeStates, setNodeStates] = useState<Record<string, NodeUpdateEventData["status"]>>({});
  const [reportPreview, setReportPreview] = useState<Partial<DesignReviewReport> | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setStatus("pending");
    setThinkingLog([]);
    setToolTimeline([]);
    setNodeStates({});
    setReportPreview(null);
    setReportId(null);
    setDurationMs(null);
    setError(null);
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const run = useCallback(
    async (
      sessionId: string,
      req: Omit<DesignReviewRequest, "stream" | "session_id">,
    ) => {
      abort();
      const ac = new AbortController();
      abortRef.current = ac;
      reset();
      setStatus("running");

      // 用 ref 跟踪最新 status，避免闭包陷阱：
      // 之前用 `status !== "error"` 判断时，闭包里的 status 是 run() 调用瞬间的快照，
      // 不会反映事件处理中 setStatus("error") 的更新，导致错误被静默吞掉后还显示 "completed"。
      const statusRef = { current: "running" as DesignReviewStatus };

      try {
        for await (const evt of designReviewService.run(sessionId, req, ac.signal)) {
          applyReviewEvent(evt, {
            setStatus: (s) => {
              statusRef.current = s;
              setStatus(s);
            },
            setThinkingLog,
            setToolTimeline,
            setNodeStates,
            setReportPreview,
            setReportId,
            setDurationMs,
            setError,
          });
        }
        // 仅当事件流没有显式标记为 error 时才标记 completed
        if (statusRef.current !== "error") setStatus("completed");
      } catch (err) {
        if ((err as { name?: string }).name === "AbortError") {
          setStatus("pending");
          return;
        }
        setError((err as Error).message ?? "未知错误");
        setStatus("error");
      }
    },
    // status 用 statusRef 跟踪最新值，不再读闭包里的 state（避免闭包陷阱）
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [abort, reset],
  );

  return {
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
    reset,
  };
}

interface ApplyArgs {
  setStatus: (s: DesignReviewStatus) => void;
  setThinkingLog: React.Dispatch<React.SetStateAction<ThinkingEntry[]>>;
  setToolTimeline: React.Dispatch<React.SetStateAction<ToolEntry[]>>;
  setNodeStates: React.Dispatch<React.SetStateAction<Record<string, NodeUpdateEventData["status"]>>>;
  setReportPreview: (r: Partial<DesignReviewReport>) => void;
  setReportId: (id: string | null) => void;
  setDurationMs: (ms: number | null) => void;
  setError: (e: string | null) => void;
}

function applyReviewEvent(evt: StreamEvent, ctx: ApplyArgs): void {
  // 临时调试：定位"前端拿不到事件数据"问题
  if (typeof window !== "undefined" && (window as unknown as { __drDebug?: boolean }).__drDebug) {
    // eslint-disable-next-line no-console
    console.log("[DR-EVT]", evt.event, "data=", JSON.stringify(evt.data));
  }
  switch (evt.event) {
    case "thinking": {
      const d = evt.data as { stage?: string; content?: string };
      ctx.setThinkingLog((prev) => [
        ...prev,
        {
          stage: d.stage ?? "",
          content: d.content,
          sequence: evt.sequence,
          timestamp: evt.timestamp,
        },
      ]);
      return;
    }
    case "node_update": {
      const d = evt.data as NodeUpdateEventData;
      ctx.setNodeStates((prev) => ({ ...prev, [d.node]: d.status }));
      return;
    }
    case "tool_call": {
      const d = evt.data as ToolCallEventData;
      ctx.setToolTimeline((prev) => [
        ...prev,
        {
          name: d.tool_name,
          args: d.arguments ?? {},
          tool_id: d.tool_id,
          sequence: evt.sequence,
          timestamp: evt.timestamp,
        },
      ]);
      return;
    }
    case "tool_result": {
      const d = evt.data as ToolResultEventData;
      ctx.setToolTimeline((prev) => {
        // 找到最后一个同名未填 result 的条目，填上
        const idx = [...prev].reverse().findIndex(
          (e) => e.name === d.tool_name && e.result === undefined,
        );
        if (idx === -1) {
          return [
            ...prev,
            {
              name: d.tool_name,
              args: {},
              tool_id: d.tool_id,
              result: d.result,
              result_status: d.status === "completed" ? "completed" : "error",
              sequence: evt.sequence,
              timestamp: evt.timestamp,
            },
          ];
        }
        const realIdx = prev.length - 1 - idx;
        const copy = prev.slice();
        const target = copy[realIdx];
        if (target) {
          copy[realIdx] = {
            ...target,
            result: d.result,
            result_status: d.status === "completed" ? "completed" : "error",
          };
        }
        return copy;
      });
      return;
    }
    case "message": {
      const d = evt.data as MessageEventData;
      if (d.type === "report" && d.report_data) {
        ctx.setReportPreview(d.report_data);
      }
      return;
    }
    case "done": {
      const d = evt.data as { report_id?: string; duration_ms?: number };
      if (d.report_id) ctx.setReportId(d.report_id);
      if (typeof d.duration_ms === "number") ctx.setDurationMs(d.duration_ms);
      return;
    }
    case "error": {
      // 兼容后端多种错误结构：
      //   1) { error: "msg", code: "..." }                       —— agent 抛异常的兜底
      //   2) { code: "INPUT_RESOLVE_FAILED", message: "...",      —— 输入解析失败的硬失败
      //      details: [...] }
      const d = evt.data as {
        error?: string;
        code?: string;
        message?: string;
        details?: string[];
      };
      const msg =
        d.error ??
        d.message ??
        (Array.isArray(d.details) && d.details.length > 0
          ? d.details.join("；")
          : null) ??
        (d.code ? `${d.code}` : null) ??
        "未知错误";
      ctx.setError(msg);
      ctx.setStatus("error");
      return;
    }
    default:
      return;
  }
}
