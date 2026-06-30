"use client";

import type { ReactNode } from "react";
import { SessionSidebar } from "@/components/session/SessionSidebar";

/**
 * Chat 布局 - 左侧会话侧栏 + 右侧主区
 * P2 阶段：侧栏已可新建/重命名/删除会话
 * 主区由 page 决定（P3 实施消息流）
 */
export default function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid h-[calc(100vh-7rem)] grid-cols-[288px_1fr] gap-4">
      <SessionSidebar userId="default_user" />
      <section
        className="overflow-hidden rounded-lg border border-brand-100 bg-white p-6"
        aria-label="主区"
      >
        {children}
      </section>
    </div>
  );
}
