"use client";

import { cn, formatTime } from "@/lib/utils";
import { ToolCallCard } from "./ToolCallCard";
import type { ChatMessage, ToolCall } from "@/types/chat";

export interface UserMessageProps {
  text: string;
  timestamp: string;
  isOptimistic?: boolean;
}

/** 用户消息气泡（右对齐，brand 颜色） */
export function UserMessage({ text, timestamp, isOptimistic }: UserMessageProps) {
  return (
    <div className="flex flex-col items-end gap-1" data-role="user">
      <div
        className={cn(
          "max-w-[80%] rounded-lg bg-brand-500 px-4 py-2 text-sm text-white shadow-sm",
          isOptimistic && "opacity-70",
        )}
      >
        {text}
      </div>
      <span className="text-[10px] text-gray-400">
        {formatTime(timestamp)}
        {isOptimistic && " · 发送中"}
      </span>
    </div>
  );
}

export interface AssistantMessageProps {
  text: string;
  toolCalls: ToolCall[];
  timestamp: string;
  isThinking?: boolean;
  isStreaming?: boolean;
  thinkingStage?: string;
}

/** 助手消息气泡（左对齐，含工具调用卡和思考指示器） */
export function AssistantMessage({
  text,
  toolCalls,
  timestamp,
  isThinking = false,
  isStreaming = false,
  thinkingStage,
}: AssistantMessageProps) {
  return (
    <div className="flex flex-col items-start gap-1" data-role="assistant">
      <div className="max-w-[85%] space-y-2">
        {toolCalls.length > 0 && (
          <div className="space-y-1">
            {toolCalls.map((tc, idx) => (
              <ToolCallCard key={`${tc.sequence}-${idx}`} toolCall={tc} />
            ))}
          </div>
        )}
        {isThinking && !text && (
          <ThinkingDots stage={thinkingStage} />
        )}
        {text && (
          <div
            className={cn(
              "rounded-lg border border-brand-100 bg-white px-4 py-2 text-sm text-gray-800 shadow-sm",
              "whitespace-pre-wrap break-words",
            )}
          >
            {text}
            {isStreaming && (
              <span
                className="ml-0.5 inline-block h-3 w-1.5 translate-y-0.5 animate-pulse bg-brand-500"
                aria-hidden
              />
            )}
          </div>
        )}
      </div>
      <span className="text-[10px] text-gray-400">{formatTime(timestamp)}</span>
    </div>
  );
}

export interface MessageBubbleProps {
  message: ChatMessage;
}

/** 历史消息的通用渲染（来自 backend） */
export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === "user") {
    return (
      <UserMessage
        text={message.content}
        timestamp={message.created_at}
      />
    );
  }
  // 助手消息：可能带 tool_call 列表（持久化的元数据）
  const toolCalls: ToolCall[] = Array.isArray(
    (message.metadata as Record<string, unknown> | undefined)?.["tool_calls"],
  )
    ? ((message.metadata as Record<string, unknown>)["tool_calls"] as ToolCall[])
    : [];
  return (
    <AssistantMessage
      text={message.content}
      toolCalls={toolCalls}
      timestamp={message.created_at}
    />
  );
}

function ThinkingDots({ stage }: { stage?: string }) {
  return (
    <div
      className="inline-flex items-center gap-2 rounded-lg border border-brand-100 bg-white px-4 py-2 text-sm text-gray-500"
      role="status"
      aria-live="polite"
    >
      <span className="flex gap-1" aria-hidden>
        <span className="h-1.5 w-1.5 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: "0ms" }} />
        <span className="h-1.5 w-1.5 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: "150ms" }} />
        <span className="h-1.5 w-1.5 rounded-full bg-brand-400 animate-bounce" style={{ animationDelay: "300ms" }} />
      </span>
      <span>{stage || "AI 正在思考…"}</span>
    </div>
  );
}
