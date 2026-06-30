/**
 * 对话与流式事件类型 - 严格对齐后端 api/v1/schemas/chat.py
 */

export type StreamEventType =
  | "message"
  | "tool_call"
  | "tool_result"
  | "node_update"
  | "thinking"
  | "error"
  | "done";

/** 单条流式事件（数据形态因 event 而异，故用泛型） */
export interface StreamEvent<T = Record<string, unknown>> {
  event: StreamEventType;
  data: T;
  agent_id: string;
  timestamp: string;
  sequence: number;
}

// ── 各种 event 的 data 形态 ──────────────────────────────────────────
export interface MessageEventData {
  content: string;
  type: "assistant" | "status" | "report";
  report_data?: DesignReportPayload;
  partial?: boolean;
}

export interface ThinkingEventData {
  stage: string;
  content?: string;
}

export interface NodeUpdateEventData {
  node: string;
  status: "pending" | "running" | "completed" | "error";
  message?: string;
}

export interface ToolCallEventData {
  tool_name: string;
  arguments?: Record<string, unknown>;
  tool_id?: string;
  status: "calling" | "completed" | "error";
}

export interface ToolResultEventData {
  tool_name: string;
  tool_id?: string;
  result: string;
  status: "completed" | "error";
}

export interface DoneEventData {
  task_id: string;
  session_id?: string;
  duration_ms: number;
  report_id?: string;
  tool_calls?: Array<Record<string, unknown>>;
  full_text?: string;
  agent_id?: string;
}

export interface ErrorEventData {
  error: string;
  code?: string;
}

// ── 报告 payload（嵌在 message(type=report) 内） ─────────────────────
import type { DesignReviewReport } from "./designReview";
export interface DesignReportPayload {
  report_meta?: DesignReviewReport["meta"];
  summary?: DesignReviewReport["summary"];
  items?: DesignReviewReport["items"];
  top_issues?: DesignReviewReport["top_issues"];
  action_items?: DesignReviewReport["action_items"];
  charts?: DesignReviewReport["charts"];
}

// ── 对话消息与会话 ──────────────────────────────────────────────────
export type ChatRole = "user" | "assistant" | "system" | "tool";
export type ChatMessageType = "text" | "report" | "tool_call" | "tool_result";

export interface ChatMessage {
  message_id: string;
  session_id: string;
  role: ChatRole;
  content: string;
  message_type: ChatMessageType;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface ChatSession {
  session_id: string;
  user_id: string;
  session_title: string;
  create_at: string;
  update_at: string;
  is_active: number;
  metadata: Record<string, unknown>;
}

// ── 流式事件累计状态 ──────────────────────────────────────────────────
/** 一次 tool_call + tool_result 合并后的本地状态 */
export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  tool_id?: string;
  result?: string;
  status: "calling" | "completed" | "error";
  sequence: number;
  timestamp: string;
}

/** 思考状态（来自 THINKING 事件） */
export interface ThinkingState {
  stage: string;
  content?: string;
  sequence: number;
  timestamp: string;
}

// ── ReactAgent 对话请求/响应 ─────────────────────────────────────────
export interface ReactChatRequest {
  message: string;
  session_id?: string | null;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
  stream: boolean;
  metadata?: Record<string, unknown>;
}

export interface ReactChatResponse {
  task_id: string;
  session_id: string | null;
  agent_id: string;
  full_text: string;
  tool_calls: Array<Record<string, unknown>>;
  duration_ms: number;
  message_id: string | null;
}
