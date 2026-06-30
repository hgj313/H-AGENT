/**
 * useChatSession - 通用对话会话 hook
 *
 * 单一职责：把"历史消息 + 实时流"组合成可渲染的视图模型
 *  - history 来自 useQuery（chatSessionService.messages），前端展示用
 *  - 真实 LLM 多轮上下文由后端 MemoryManager 自行从 session_id 拉取与组装
 *  - 前端不再传 history 入参（避免与后端重复组装）
 *  - send 时乐观地展示用户消息；stream 完成后 refetch history（让真实消息覆盖乐观消息）
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStreamChat } from "./useStreamChat";
import { chatSessionService } from "@/services/chatService";
import type { ChatMessage } from "@/types/chat";

export interface LiveAssistantState {
  text: string;
  toolCalls: ReturnType<typeof useStreamChat>["toolCalls"];
  isThinking: boolean;
  isStreaming: boolean;
}

export interface UseChatSessionResult {
  history: ChatMessage[];
  liveUser: string | null;
  liveAssistant: LiveAssistantState | null;
  send: (text: string) => Promise<void>;
  abort: () => void;
  status: ReturnType<typeof useStreamChat>["status"];
  error: string | null;
  isLoadingHistory: boolean;
  historyError: Error | null;
}

export function useChatSession(sessionId: string): UseChatSessionResult {
  const [liveUser, setLiveUser] = useState<string | null>(null);

  const stream = useStreamChat();

  const historyQuery = useQuery({
    queryKey: ["session", sessionId, "messages"],
    queryFn: () => chatSessionService.messages(sessionId),
    enabled: !!sessionId,
    staleTime: 0,
    refetchOnMount: "always",
  });

  // 流结束后，触发 history 重拉，让真实消息覆盖乐观消息
  useEffect(() => {
    if (stream.status === "done" || stream.status === "error") {
      void historyQuery.refetch();
    }
  }, [stream.status, historyQuery]);

  // 卸载时 abort，防止泄漏
  useEffect(() => {
    return () => {
      stream.abort();
    };
    // stream.abort 引用稳定；不把 stream 整体加入依赖以免循环
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setLiveUser(trimmed);
      try {
        await stream.send(trimmed, { sessionId });
      } catch {
        // 错误已通过 stream.error 暴露
      } finally {
        setLiveUser(null);
      }
    },
    [sessionId, stream],
  );

  const showLiveAssistant =
    stream.status === "thinking" || stream.status === "streaming";
  const liveAssistant: LiveAssistantState | null = showLiveAssistant
    ? {
        text: stream.messageBuffer,
        toolCalls: stream.toolCalls,
        isThinking: stream.status === "thinking",
        isStreaming: stream.status === "streaming",
      }
    : null;

  return {
    history: historyQuery.data?.messages ?? [],
    liveUser,
    liveAssistant,
    send,
    abort: stream.abort,
    status: stream.status,
    error: stream.error,
    isLoadingHistory: historyQuery.isLoading,
    historyError: historyQuery.error,
  };
}
