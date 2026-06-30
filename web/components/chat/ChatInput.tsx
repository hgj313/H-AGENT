"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/common/Button";

export interface ChatInputProps {
  onSend: (text: string) => Promise<void>;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  placeholder?: string;
}

/** 对话输入框 - 自动 resize / Enter 发送 / Shift+Enter 换行 / 发送↔停止切换 */
export function ChatInput({
  onSend,
  onStop,
  isStreaming,
  disabled,
  placeholder,
}: ChatInputProps) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // 自动 resize
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [text]);

  const send = async () => {
    const trimmed = text.trim();
    if (!trimmed || pending || disabled) return;
    setPending(true);
    setText("");
    try {
      await onSend(trimmed);
    } finally {
      setPending(false);
      taRef.current?.focus();
    }
  };

  const stop = () => {
    onStop();
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div
      className={cn(
        "flex items-end gap-2 border-t border-brand-100 bg-white p-3",
      )}
    >
      <textarea
        ref={taRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKey}
        rows={1}
        disabled={disabled || pending}
        placeholder={
          placeholder ??
          (isStreaming ? "AI 正在回复…（可点停止）" : "输入消息，回车发送，Shift+Enter 换行")
        }
        aria-label="消息输入框"
        className={cn(
          "flex-1 resize-none rounded-md border border-brand-200 bg-white px-3 py-2 text-sm",
          "focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-400",
          "disabled:cursor-not-allowed disabled:opacity-60",
          "max-h-[200px] overflow-y-auto",
        )}
      />
      {isStreaming ? (
        <Button variant="danger" onClick={stop} aria-label="停止生成">
          停止
        </Button>
      ) : (
        <Button
          onClick={send}
          disabled={!text.trim() || pending || disabled}
          loading={pending}
          aria-label="发送消息"
        >
          发送
        </Button>
      )}
    </div>
  );
}
