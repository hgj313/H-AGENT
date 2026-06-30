/**
 * useDeleteSession - 删除会话 mutation（含乐观移除）
 * 单一职责：删除 + 乐观移除 + 清空当前选中
 */
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { chatSessionService } from "@/services/chatService";
import { useSessionStore } from "@/store/useSessionStore";
import type { ChatSession } from "@/types/chat";

interface OptimisticContext {
  previous?: Array<[readonly unknown[], unknown]>;
}

export function useDeleteSession() {
  const qc = useQueryClient();
  const clear = useSessionStore((s) => s.clear);
  const currentId = useSessionStore((s) => s.currentSessionId);

  return useMutation<{ ok: boolean }, Error, string, OptimisticContext>({
    mutationFn: (sessionId) => chatSessionService.delete(sessionId),
    onMutate: async (sessionId) => {
      await qc.cancelQueries({ queryKey: ["sessions"] });
      const previous = qc.getQueriesData({ queryKey: ["sessions"] });
      qc.setQueriesData<{ total: number; sessions: ChatSession[] }>(
        { queryKey: ["sessions"] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: Math.max(0, old.total - 1),
            sessions: old.sessions.filter((s) => s.session_id !== sessionId),
          };
        },
      );
      // 若删除的是当前选中，立即清空 store
      if (currentId === sessionId) clear();
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) {
        for (const [key, value] of ctx.previous) {
          qc.setQueryData(key, value);
        }
      }
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}
