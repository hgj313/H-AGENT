/**
 * useUpdateSession - 会话更新 mutation（含乐观重命名）
 * 单一职责：更新 + 乐观回滚 + 缓存失效
 */
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { chatSessionService } from "@/services/chatService";
import { useSessionStore } from "@/store/useSessionStore";
import type { ChatSession } from "@/types/chat";

export interface UpdateSessionVars {
  sessionId: string;
  sessionTitle?: string;
  metadata?: Record<string, unknown>;
}

interface OptimisticContext {
  previous?: Array<[readonly unknown[], unknown]>;
}

export function useUpdateSession() {
  const qc = useQueryClient();
  const setCurrent = useSessionStore((s) => s.setCurrent);
  const currentId = useSessionStore((s) => s.currentSessionId);

  return useMutation<ChatSession, Error, UpdateSessionVars, OptimisticContext>({
    mutationFn: ({ sessionId, ...body }) =>
      chatSessionService.update(sessionId, body),
    onMutate: async ({ sessionId, sessionTitle, metadata }) => {
      await qc.cancelQueries({ queryKey: ["sessions"] });
      const previous = qc.getQueriesData({ queryKey: ["sessions"] });
      // 乐观更新所有匹配的 sessions 缓存
      qc.setQueriesData<{ total: number; sessions: ChatSession[] }>(
        { queryKey: ["sessions"] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            sessions: old.sessions.map((s) =>
              s.session_id === sessionId
                ? {
                    ...s,
                    session_title: sessionTitle ?? s.session_title,
                    metadata: metadata ? { ...s.metadata, ...metadata } : s.metadata,
                    update_at: new Date().toISOString(),
                  }
                : s,
            ),
          };
        },
      );
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      // 回滚
      if (ctx?.previous) {
        for (const [key, value] of ctx.previous) {
          qc.setQueryData(key, value);
        }
      }
    },
    onSuccess: (sess, vars) => {
      // 若是当前会话，同步 store 中的 title
      if (currentId === vars.sessionId) {
        setCurrent(sess.session_id, sess.session_title);
      }
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}
