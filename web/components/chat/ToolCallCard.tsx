"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { ToolCall } from "@/types/chat";

const STATUS_LABEL: Record<ToolCall["status"], string> = {
  calling: "调用中",
  completed: "已完成",
  error: "失败",
};

const STATUS_CLASS: Record<ToolCall["status"], string> = {
  calling: "bg-blue-50 border-blue-200 text-blue-700",
  completed: "bg-green-50 border-green-200 text-green-700",
  error: "bg-red-50 border-red-200 text-red-700",
};

const STATUS_DOT: Record<ToolCall["status"], string> = {
  calling: "bg-blue-500 animate-pulse",
  completed: "bg-green-500",
  error: "bg-red-500",
};

export interface ToolCallCardProps {
  toolCall: ToolCall;
}

/** 工具调用卡：可展开 args / result */
export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasResult = toolCall.result !== undefined;

  return (
    <div
      className={cn(
        "rounded-md border text-xs",
        STATUS_CLASS[toolCall.status],
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={expanded}
      >
        <span
          className={cn("inline-block h-2 w-2 rounded-full", STATUS_DOT[toolCall.status])}
          aria-hidden
        />
        <span className="font-mono font-medium">{toolCall.name}</span>
        <span className="text-[10px] opacity-70">
          · {STATUS_LABEL[toolCall.status]}
        </span>
        <span className="ml-auto text-[10px] opacity-50">
          #{toolCall.sequence}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-current/10 px-3 py-2 space-y-2">
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wide opacity-60">
              参数
            </div>
            <pre className="overflow-x-auto rounded bg-white/50 p-2 font-mono text-[11px]">
              {JSON.stringify(toolCall.args, null, 2)}
            </pre>
          </div>
          {hasResult && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-wide opacity-60">
                结果
              </div>
              <pre className="max-h-40 overflow-auto rounded bg-white/50 p-2 font-mono text-[11px] whitespace-pre-wrap break-words">
                {truncate(toolCall.result ?? "", 1000)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "\n…（已截断）" : s;
}
