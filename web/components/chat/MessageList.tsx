"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { MessageBubble, UserMessage, AssistantMessage } from "./MessageBubble";
import { Skeleton } from "@/components/common/Skeleton";
import type { ChatMessage } from "@/types/chat";
import type { LiveAssistantState } from "@/hooks/useChatSession";

export interface MessageListProps {
  history: ChatMessage[];
  liveUser: string | null;
  liveAssistant: LiveAssistantState | null;
  isLoadingHistory: boolean;
  historyError: Error | null;
  onRetryHistory: () => void;
}

/** 消息列表 - 滚动容器 + 自动滚到底（仅用户未滚动时） */
export function MessageList({
  history,
  liveUser,
  liveAssistant,
  isLoadingHistory,
  historyError,
  onRetryHistory,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [showJump, setShowJump] = useState(false);

  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const atBottom = distance < 80;
    setAutoScroll(atBottom);
    setShowJump(!atBottom);
  };

  // 列表/流内容变化时自动滚到底（仅在 atBottom 时）
  useEffect(() => {
    if (!autoScroll) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [
    history.length,
    liveUser,
    liveAssistant?.text,
    liveAssistant?.toolCalls.length,
    liveAssistant?.isThinking,
    liveAssistant?.isStreaming,
    autoScroll,
  ]);

  // 初次挂载滚动到底
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, []);

  const hasContent =
    history.length > 0 || liveUser !== null || liveAssistant !== null;

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        onScroll={onScroll}
        className="h-full overflow-y-auto px-1 py-4"
        role="log"
        aria-live="polite"
        aria-label="对话消息"
      >
        {isLoadingHistory && history.length === 0 && (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        )}

        {historyError && history.length === 0 && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">
            历史消息加载失败：{historyError.message}
            <button
              type="button"
              onClick={onRetryHistory}
              className="ml-2 underline"
            >
              重试
            </button>
          </div>
        )}

        {!hasContent && !isLoadingHistory && (
          <div className="flex h-full flex-col items-center justify-center text-center text-sm text-gray-400">
            <p>开始你的第一次对话吧</p>
            <p className="mt-1 text-xs">输入消息，回车发送</p>
          </div>
        )}

        <div className="flex flex-col gap-3">
          {history.map((m) => (
            <MessageBubble key={m.message_id} message={m} />
          ))}

          {liveUser && (
            <UserMessage
              text={liveUser}
              timestamp={new Date().toISOString()}
              isOptimistic
            />
          )}

          {liveAssistant && (
            <AssistantMessage
              text={liveAssistant.text}
              toolCalls={liveAssistant.toolCalls}
              timestamp={new Date().toISOString()}
              isThinking={liveAssistant.isThinking}
              isStreaming={liveAssistant.isStreaming}
              thinkingStage={
                (liveAssistant as { thinkingStage?: string }).thinkingStage
              }
            />
          )}
        </div>

        <div ref={bottomRef} />
      </div>

      {showJump && (
        <button
          type="button"
          onClick={() => {
            setAutoScroll(true);
            bottomRef.current?.scrollIntoView({ behavior: "smooth" });
          }}
          className={cn(
            "absolute bottom-4 left-1/2 -translate-x-1/2",
            "rounded-full border border-brand-200 bg-white px-3 py-1 text-xs text-brand-500 shadow-md",
            "hover:bg-brand-50",
          )}
          aria-label="跳到最新消息"
        >
          ↓ 跳到最新
        </button>
      )}
    </div>
  );
}
