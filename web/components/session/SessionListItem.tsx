"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { useUpdateSession } from "@/hooks/useUpdateSession";
import { useDeleteSession } from "@/hooks/useDeleteSession";
import type { ChatSession } from "@/types/chat";

export interface SessionListItemProps {
  session: ChatSession;
  isActive: boolean;
  onSelect: () => void;
}

/** 单条会话：inline 编辑 + 删除 */
export function SessionListItem({ session, isActive, onSelect }: SessionListItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(session.session_title);
  const inputRef = useRef<HTMLInputElement>(null);
  const updateMut = useUpdateSession();
  const deleteMut = useDeleteSession();

  // 外部 title 变化时同步 draft（仅非编辑态）
  useEffect(() => {
    if (!isEditing) setDraft(session.session_title);
  }, [session.session_title, isEditing]);

  // 进入编辑态聚焦
  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  const commit = async () => {
    const next = draft.trim();
    if (next && next !== session.session_title) {
      try {
        await updateMut.mutateAsync({
          sessionId: session.session_id,
          sessionTitle: next,
        });
      } catch {
        setDraft(session.session_title);
      }
    } else {
      setDraft(session.session_title);
    }
    setIsEditing(false);
  };

  const cancel = () => {
    setDraft(session.session_title);
    setIsEditing(false);
  };

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`确认删除会话「${session.session_title}」？`)) return;
    try {
      await deleteMut.mutateAsync(session.session_id);
    } catch {
      // 乐观更新已回滚，错误由 onError 自行处理
    }
  };

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsEditing(true);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={isEditing ? undefined : onSelect}
      onKeyDown={(e) => {
        if (isEditing) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
        "hover:bg-brand-50 cursor-pointer",
        isActive && "bg-brand-100 text-brand-600 font-medium",
      )}
    >
      {isEditing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void commit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              cancel();
            }
          }}
          onClick={(e) => e.stopPropagation()}
          maxLength={120}
          aria-label="编辑会话标题"
          className="flex-1 rounded border border-brand-300 bg-white px-1 py-0.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-400"
        />
      ) : (
        <span className="flex-1 truncate" title={session.session_title}>
          {session.session_title}
        </span>
      )}

      {!isEditing && (
        <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
          <button
            type="button"
            onClick={startEdit}
            aria-label="重命名"
            title="重命名"
            className="rounded p-1 text-gray-500 hover:bg-brand-200 hover:text-brand-600"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z" />
            </svg>
          </button>
          <button
            type="button"
            onClick={handleDelete}
            aria-label="删除"
            title="删除"
            disabled={deleteMut.isPending}
            className="rounded p-1 text-gray-500 hover:bg-red-100 hover:text-red-600 disabled:opacity-50"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M3 6h18" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
              <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
}
