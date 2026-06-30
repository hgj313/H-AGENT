"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { chatSessionService } from "@/services/chatService";
import { useSessionStore } from "@/store/useSessionStore";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { Button } from "@/components/common/Button";
import { ROUTES } from "@/constants/routes";

/**
 * 通用对话 - 选中会话视图
 *  - 加载 session 元信息
 *  - 同步 URL → store
 *  - 渲染 ChatPanel（消息流 + 输入框）
 */
export default function ChatSessionPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const setCurrent = useSessionStore((s) => s.setCurrent);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["session", id],
    queryFn: () => chatSessionService.get(id),
    retry: false,
  });

  useEffect(() => {
    if (data) setCurrent(data.session_id, data.session_title);
  }, [data, setCurrent]);

  if (isLoading) {
    return <p className="text-sm text-gray-500">加载中…</p>;
  }
  if (isError) {
    return (
      <div className="text-sm text-red-600">
        会话加载失败：{(error as Error)?.message ?? "未知错误"}
        <div className="mt-2">
          <Link href={ROUTES.chat}>
            <Button variant="secondary">返回对话列表</Button>
          </Link>
        </div>
      </div>
    );
  }
  if (!data) return null;

  return <ChatPanel sessionId={id} sessionTitle={data.session_title} />;
}
