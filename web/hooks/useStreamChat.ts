/**
 * useStreamChat - 通用对话流式 hook
 *
 * 单一职责：
 *   - 调用 reactAgentService.stream() 拉 SSE
 *   - 累积：messageBuffer（文本） + toolCalls（工具调用） + thinking（当前思考）
 *   - 暴露：status / 累积状态 / send / abort / reset
 *
 * 业务事件（node_update / done / error）通过状态暴露，复杂解析交给消费方 hook（如 useChatSession）。
 */

"use client";

import { useCallback, useRef, useState } from "react";
import { reactAgentService } from "@/services/chatService";
import type {
  MessageEventData,
  StreamEvent,
  StreamEventType,
  ThinkingState,
  ToolCall,
  ToolCallEventData,
  ToolResultEventData,
} from "@/types/chat";

export type StreamStatus = "idle" | "thinking" | "streaming" | "done" | "error";

export interface UseStreamChatResult {
  status: StreamStatus;
  messageBuffer: string;
  toolCalls: ToolCall[];
  thinking: ThinkingState | null;
  lastEvent: StreamEvent | null;
  error: string | null;
  send: (
    message: string,
    options?: {
      sessionId?: string;
      history?: Array<{ role: "user" | "assistant"; content: string }>;
    },
  ) => Promise<void>;
  abort: () => void;
  reset: () => void;
}

export function useStreamChat(
  onEvent?: (evt: StreamEvent) => void,
): UseStreamChatResult {
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [messageBuffer, setMessageBuffer] = useState("");
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [thinking, setThinking] = useState<ThinkingState | null>(null);
  const [lastEvent, setLastEvent] = useState<StreamEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setMessageBuffer("");
    setToolCalls([]);
    setThinking(null);
    setLastEvent(null);
    setError(null);
    setStatus("idle");
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("idle");
  }, []);

  const send = useCallback(
    async (
      message: string,
      options?: {
        sessionId?: string;
        history?: Array<{ role: "user" | "assistant"; content: string }>;
      },
    ) => {
      if (!message.trim()) return;
      abort();
      const ac = new AbortController();
      abortRef.current = ac;
      reset();
      setStatus("thinking");

      try {
        for await (const evt of reactAgentService.stream(
          {
            message,
            session_id: options?.sessionId ?? null,
            history: options?.history ?? [],
          },
          ac.signal,
        )) {
          setLastEvent(evt);
          onEvent?.(evt);
          applyEvent(evt, {
            setMessageBuffer,
            setToolCalls,
            setThinking,
            setStatus,
            setError,
          });
        }
      } catch (err) {
        if ((err as { name?: string }).name === "AbortError") {
          return;
        }
        setError((err as Error).message ?? "未知错误");
        setStatus("error");
      }
    },
    [abort, onEvent, reset],
  );

  return {
    status,
    messageBuffer,
    toolCalls,
    thinking,
    lastEvent,
    error,
    send,
    abort,
    reset,
  };
}

interface Setters {
  setMessageBuffer: React.Dispatch<React.SetStateAction<string>>;
  setToolCalls: React.Dispatch<React.SetStateAction<ToolCall[]>>;
  setThinking: React.Dispatch<React.SetStateAction<ThinkingState | null>>;
  setStatus: (s: StreamStatus) => void;
  setError: (e: string | null) => void;
}

function applyEvent(evt: StreamEvent, s: Setters): void {
  const t: StreamEventType = evt.event;
  switch (t) {
    case "thinking": {
      const d = evt.data as { stage?: string; content?: string };
      s.setThinking({
        stage: d.stage ?? "",
        content: d.content,
        sequence: evt.sequence,
        timestamp: evt.timestamp,
      });
      s.setStatus("thinking");
      break;
    }
    case "message": {
      const d = evt.data as MessageEventData;
      if (d?.type === "assistant" && typeof d.content === "string") {
        s.setMessageBuffer((prev) => prev + d.content);
        s.setThinking(null);
        s.setStatus("streaming");
      }
      break;
    }
    case "tool_call": {
      const d = evt.data as ToolCallEventData;
      s.setToolCalls((prev) => [
        ...prev,
        {
          name: d.tool_name,
          args: d.arguments ?? {},
          tool_id: d.tool_id,
          status: "calling",
          sequence: evt.sequence,
          timestamp: evt.timestamp,
        },
      ]);
      break;
    }
    case "tool_result": {
      const d = evt.data as ToolResultEventData;
      s.setToolCalls((prev) => {
        // 倒序找第一个同名且未填 result 的项
        const idx = [...prev]
          .reverse()
          .findIndex((tc) => tc.name === d.tool_name && tc.result === undefined);
        if (idx === -1) {
          return [
            ...prev,
            {
              name: d.tool_name,
              args: {},
              tool_id: d.tool_id,
              result: d.result,
              status: d.status === "completed" ? "completed" : "error",
              sequence: evt.sequence,
              timestamp: evt.timestamp,
            },
          ];
        }
        const realIdx = prev.length - 1 - idx;
        const copy = prev.slice();
        const target = copy[realIdx];
        if (target) {
          copy[realIdx] = {
            ...target,
            result: d.result,
            status: d.status === "completed" ? "completed" : "error",
          };
        }
        return copy;
      });
      break;
    }
    case "node_update":
      // 节点状态由消费方 hook 决定是否使用
      break;
    case "done":
      s.setStatus("done");
      s.setThinking(null);
      break;
    case "error": {
      const d = evt.data as { error?: string };
      s.setError(d?.error ?? "未知错误");
      s.setStatus("error");
      break;
    }
    default:
      break;
  }
}
