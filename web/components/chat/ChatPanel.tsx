"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useChatSession } from "@/hooks/useChatSession";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { cn } from "@/lib/utils";

export interface ChatPanelProps {
  sessionId: string;
  sessionTitle: string;
}

const STATUS_LABEL: Record<ReturnType<typeof useChatSession>["status"], string> = {
  idle: "空闲",
  thinking: "AI 思考中",
  streaming: "AI 回复中",
  done: "已完成",
  error: "错误",
};

const STATUS_DOT: Record<ReturnType<typeof useChatSession>["status"], string> = {
  idle: "bg-gray-300",
  thinking: "bg-blue-500 animate-pulse",
  streaming: "bg-blue-500 animate-pulse",
  done: "bg-green-500",
  error: "bg-red-500",
};

/** ChatPanel - 通用对话主面板（消息流 + 输入框 + 状态） */
export function ChatPanel({ sessionId, sessionTitle }: ChatPanelProps) {
  const qc = useQueryClient();
  const {
    history,
    liveUser,
    liveAssistant,
    send,
    abort,
    status,
    error,
    isLoadingHistory,
    historyError,
  } = useChatSession(sessionId);

  const isStreaming = status === "thinking" || status === "streaming";

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-brand-100 pb-3">
        <h1
          className="truncate text-lg font-semibold text-brand-500"
          title={sessionTitle}
        >
          {sessionTitle}
        </h1>
        <div
          className="flex items-center gap-1.5 text-xs text-gray-500"
          aria-live="polite"
        >
          <span
            className={cn("inline-block h-2 w-2 rounded-full", STATUS_DOT[status])}
            aria-hidden
          />
          {STATUS_LABEL[status]}
        </div>
      </header>

      <MessageList
        history={history}
        liveUser={liveUser}
        liveAssistant={liveAssistant}
        isLoadingHistory={isLoadingHistory}
        historyError={historyError}
        onRetryHistory={() =>
          void qc.invalidateQueries({
            queryKey: ["session", sessionId, "messages"],
          })
        }
      />

      {error && (
        <p
          role="alert"
          className="border-t border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {error}
        </p>
      )}

      <ChatInput
        onSend={send}
        onStop={abort}
        isStreaming={isStreaming}
      />
    </div>
  );
}
