/**
 * 对话服务 - 会话 + 消息 + 通用对话流
 */

import { apiRequest } from "@/api/apiClient";
import { streamPostSSE } from "@/api/sseClient";
import type {
  ChatMessage,
  ChatSession,
  ReactChatRequest,
  ReactChatResponse,
  StreamEvent,
  MessageEventData,
} from "@/types/chat";

// ── 会话 CRUD ───────────────────────────────────────────────────────
export const chatSessionService = {
  create: (params: {
    user_id?: string;
    session_title?: string;
    metadata?: Record<string, unknown>;
  }): Promise<ChatSession> =>
    apiRequest<ChatSession>("/api/v1/chat/sessions", {
      method: "POST",
      body: params,
    }),

  list: (params: {
    user_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ total: number; sessions: ChatSession[] }> =>
    apiRequest("/api/v1/chat/sessions", { query: params }),

  get: (sessionId: string): Promise<ChatSession> =>
    apiRequest<ChatSession>(
      `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`,
    ),

  update: (
    sessionId: string,
    params: { session_title?: string; metadata?: Record<string, unknown> },
  ): Promise<ChatSession> =>
    apiRequest<ChatSession>(
      `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`,
      { method: "PUT", body: params },
    ),

  delete: (sessionId: string): Promise<{ ok: boolean }> =>
    apiRequest(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),

  messages: (sessionId: string): Promise<{ messages: ChatMessage[] }> =>
    apiRequest(`/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/messages`),
};

// ── ReactAgent 对话 ──────────────────────────────────────────────────
export const reactAgentService = {
  /** 非流式对话 */
  chat: (req: ReactChatRequest): Promise<ReactChatResponse> =>
    apiRequest<ReactChatResponse>("/api/v1/react-agent/chat", {
      method: "POST",
      body: { ...req, stream: false },
    }),

  /** 流式对话（SSE） - 产出 typed StreamEvent */
  stream: (
    req: Omit<ReactChatRequest, "stream">,
    signal?: AbortSignal,
  ): AsyncGenerator<StreamEvent<MessageEventData | Record<string, unknown>>, void, void> =>
    streamPostSSE<MessageEventData | Record<string, unknown>>(
      "/api/v1/react-agent/chat",
      { body: { ...req, stream: true }, signal },
    ),
};
