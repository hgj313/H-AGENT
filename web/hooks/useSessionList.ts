/**
 * useSessionList - 会话列表查询
 * 单一职责：拉取 + 过滤
 */
"use client";

import { useQuery } from "@tanstack/react-query";
import { chatSessionService } from "@/services/chatService";
import type { ChatSession } from "@/types/chat";

export interface UseSessionListParams {
  userId?: string;
  agentId?: string;
  limit?: number;
  /** 仅前端过滤；后端不分页过滤 agentId */
  filterAgentId?: boolean;
}

export function useSessionList(params: UseSessionListParams = {}) {
  const { userId, agentId, limit = 100, filterAgentId = false } = params;
  return useQuery<{ total: number; sessions: ChatSession[] }, Error>({
    queryKey: ["sessions", { userId, limit }],
    queryFn: () => chatSessionService.list({ user_id: userId, limit }),
    enabled: userId !== undefined,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    select: (data) => {
      if (!filterAgentId || !agentId) return data;
      const filtered = data.sessions.filter(
        (s) => (s.metadata?.["agent_id"] as string | undefined) === agentId,
      );
      return { total: filtered.length, sessions: filtered };
    },
  });
}
