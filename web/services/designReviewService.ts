/**
 * 设计审查服务 - 任务会话 + 流式审查 + 报告拉取
 *
 * 接口契约（与 P0 后端 REST 路径对齐）：
 *   POST /api/v1/design-review/sessions              创建会话
 *   POST /api/v1/design-review/sessions/{id}/run     流式触发审查（SSE）
 *   GET  /api/v1/design-review/sessions/{id}/report  拉取完整报告
 *
 * 后端统一响应包装：{ success: bool, session|sessions: {...} | [...] }
 * 此处 service 负责解包，前端只接触扁平数据。
 *
 * 注：后端 DesignReviewAgent 的 SSE 流通过 streamPostSSE 复用通用 SSE 客户端。
 */

import { apiRequest } from "@/api/apiClient";
import { streamPostSSE } from "@/api/sseClient";
import type { DesignReviewReport, DesignReviewRequest } from "@/types/designReview";
import type { StreamEvent } from "@/types/chat";

/** 后端原始响应包装 */
interface ApiEnvelope<T> {
  success?: boolean;
  session?: T;
  sessions?: T;
  report?: T;
  // 兼容扁平响应（防御性）
  [key: string]: unknown;
}

export interface DesignReviewSession {
  dr_session_id: string;  // 后端原始字段名（保持与 persistence 对齐）
  user_id: string;
  session_title: string;
  prd_path: string;
  image_urls: string[];
  created_at: string;
  status: "pending" | "running" | "completed" | "failed";
}

export const designReviewService = {
  /** 创建审查会话 */
  createSession: async (params: {
    user_id?: string;
    prd_path: string;
    image_urls: string[];
  }): Promise<DesignReviewSession> => {
    const resp = await apiRequest<ApiEnvelope<DesignReviewSession>>(
      "/api/v1/design-review/sessions",
      { method: "POST", body: params },
    );
    if (!resp || !resp.session) {
      throw new Error("后端返回无 session 字段：" + JSON.stringify(resp));
    }
    return resp.session;
  },

  /** 流式触发审查 */
  run: (
    sessionId: string,
    req: Omit<DesignReviewRequest, "stream" | "session_id">,
    signal?: AbortSignal,
  ): AsyncGenerator<StreamEvent, void, void> =>
    streamPostSSE(`/api/v1/design-review/sessions/${encodeURIComponent(sessionId)}/run`, {
      body: { ...req, session_id: sessionId, stream: true },
      signal,
    }),

  /** 拉取完整报告 */
  getReport: async (sessionId: string): Promise<DesignReviewReport> => {
    // 后端统一响应：{ success: true, report: {...} }
    const resp = await apiRequest<ApiEnvelope<DesignReviewReport>>(
      `/api/v1/design-review/sessions/${encodeURIComponent(sessionId)}/report`,
    );
    const report = resp?.report;
    if (!report) {
      throw new Error("后端返回无 report 字段：" + JSON.stringify(resp));
    }
    return report;
  },
};
