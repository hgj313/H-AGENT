/**
 * useCreateSession - 新建会话 mutation
 * 单一职责：创建 + 缓存失效 + 选中
 */
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { chatSessionService } from "@/services/chatService";
import { useSessionStore } from "@/store/useSessionStore";
import type { ChatSession } from "@/types/chat";

export interface CreateSessionVars {
  userId?: string;
  sessionTitle?: string;
  agentId?: string;
  metadata?: Record<string, unknown>;
}

export function useCreateSession() {
  const qc = useQueryClient();
  const setCurrent = useSessionStore((s) => s.setCurrent);

  return useMutation<ChatSession, Error, CreateSessionVars>({
    mutationFn: async ({ agentId, metadata, ...rest }) => {
      const meta: Record<string, unknown> = { ...(metadata ?? {}) };
      if (agentId) meta["agent_id"] = agentId;
      return chatSessionService.create({
        user_id: rest.userId,
        session_title: rest.sessionTitle,
        metadata: Object.keys(meta).length > 0 ? meta : undefined,
      });
    },
    onSuccess: (sess) => {
      setCurrent(sess.session_id, sess.session_title);
      void qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}
