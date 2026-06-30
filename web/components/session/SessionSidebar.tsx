"use client";

import { useRouter } from "next/navigation";
import { useSessionList } from "@/hooks/useSessionList";
import { useSessionStore } from "@/store/useSessionStore";
import { SessionListItem } from "./SessionListItem";
import { CreateSessionButton } from "./CreateSessionButton";
import { Skeleton } from "@/components/common/Skeleton";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils";

export interface SessionSidebarProps {
  userId?: string;
  agentId?: string;
}

/** 会话侧栏 - 包含新建按钮 + 列表 */
export function SessionSidebar({ userId, agentId }: SessionSidebarProps) {
  const router = useRouter();
  const currentId = useSessionStore((s) => s.currentSessionId);
  const setCurrent = useSessionStore((s) => s.setCurrent);
  const { data, isLoading, isError, error, refetch } = useSessionList({
    userId,
    agentId,
    filterAgentId: !!agentId,
  });

  return (
    <aside
      className={cn(
        "flex h-[calc(100vh-7rem)] w-72 shrink-0 flex-col rounded-lg border border-brand-100 bg-white",
      )}
      aria-label="会话侧栏"
    >
      <div className="border-b border-brand-100 p-3">
        <CreateSessionButton userId={userId} agentId={agentId} />
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {isLoading && (
          <div className="space-y-2 p-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-7" />
            ))}
          </div>
        )}

        {isError && (
          <div className="p-2 text-xs text-red-600">
            加载失败
            <button
              type="button"
              onClick={() => refetch()}
              className="ml-1 underline"
            >
              重试
            </button>
            <p className="mt-1 break-all text-[10px] text-red-400">
              {error?.message}
            </p>
          </div>
        )}

        {data && data.sessions.length === 0 && (
          <p className="px-2 py-4 text-center text-xs text-gray-400">
            还没有会话
          </p>
        )}

        {data && data.sessions.length > 0 && (
          <ul className="space-y-0.5">
            {data.sessions.map((s) => (
              <li key={s.session_id}>
                <SessionListItem
                  session={s}
                  isActive={s.session_id === currentId}
                  onSelect={() => {
                    setCurrent(s.session_id, s.session_title);
                    router.push(ROUTES.chatSession(s.session_id));
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
