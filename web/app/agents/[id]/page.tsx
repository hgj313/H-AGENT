"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { agentService } from "@/services/agentService";
import { useSessionList } from "@/hooks/useSessionList";
import { useCreateSession } from "@/hooks/useCreateSession";
import { ROUTES } from "@/constants/routes";
import { Skeleton } from "@/components/common/Skeleton";
import { Button } from "@/components/common/Button";
import { AgentActionButtons } from "@/components/agent/AgentActionButtons";

/**
 * Agent 详情页（P2 增强）
 *  - Agent 元信息
 *  - 操作按钮（pause/resume/restart）
 *  - 相关会话（按 agentId 过滤）
 *  - "开始对话"创建会话并跳转
 */
export default function AgentDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const router = useRouter();
  const create = useCreateSession();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["agent", id],
    queryFn: () => agentService.get(id),
  });

  const { data: sessionsData, isLoading: sessionsLoading } = useSessionList({
    userId: "default_user",
    agentId: id,
    filterAgentId: true,
  });

  const handleStart = async () => {
    const sess = await create.mutateAsync({ userId: "default_user", agentId: id });
    router.push(ROUTES.chatSession(sess.session_id));
  };

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton variant="rect" className="h-32" />
        <Skeleton variant="text" className="h-4 w-1/2" />
        <Skeleton variant="text" className="h-4 w-2/3" />
      </div>
    );
  }

  if (isError) {
    return (
      <p className="text-sm text-red-600">加载失败：{error?.message}</p>
    );
  }
  if (!data) return null;

  const { config, state, is_available } = data;

  return (
    <article className="mx-auto max-w-3xl space-y-6">
      <header className="rounded-lg border border-brand-100 bg-white p-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-brand-500">
              {config.name}
            </h1>
            <p className="mt-1 text-sm text-gray-500">{config.description}</p>
            <div className="mt-3 flex flex-wrap gap-1">
              {config.capabilities.map((cap) => (
                <span
                  key={cap}
                  className="rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-500"
                >
                  {cap}
                </span>
              ))}
            </div>
          </div>
          <div className="text-right text-xs text-gray-500">
            <div>状态：{state.status}</div>
            <div>错误：{state.error_count}</div>
            <div>可用：{is_available ? "是" : "否"}</div>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <Button
            onClick={handleStart}
            loading={create.isPending}
            disabled={!is_available}
          >
            开始对话
          </Button>
          <AgentActionButtons agentId={id} currentStatus={state.status} />
          <Link href={ROUTES.agentHub}>
            <Button variant="ghost">返回 Agent 中心</Button>
          </Link>
        </div>
      </header>

      <section className="rounded-lg border border-brand-100 bg-white p-6 text-sm text-gray-600">
        <h2 className="mb-2 text-base font-medium text-brand-500">详情</h2>
        <dl className="grid grid-cols-2 gap-2">
          <dt className="text-gray-400">类型</dt>
          <dd>{config.agent_type}</dd>
          <dt className="text-gray-400">版本</dt>
          <dd>{config.version}</dd>
          <dt className="text-gray-400">最大并发</dt>
          <dd>{config.max_concurrent}</dd>
          <dt className="text-gray-400">超时</dt>
          <dd>{config.timeout}s</dd>
        </dl>
      </section>

      <section className="rounded-lg border border-brand-100 bg-white p-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-medium text-brand-500">相关会话</h2>
          <Button
            variant="secondary"
            onClick={handleStart}
            loading={create.isPending}
            disabled={!is_available}
          >
            + 新建会话
          </Button>
        </div>
        {sessionsLoading && (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-6" />
            ))}
          </div>
        )}
        {sessionsData && sessionsData.sessions.length === 0 && (
          <p className="py-4 text-center text-sm text-gray-400">
            还没有相关会话
          </p>
        )}
        {sessionsData && sessionsData.sessions.length > 0 && (
          <ul className="divide-y divide-brand-50">
            {sessionsData.sessions.slice(0, 10).map((s) => (
              <li key={s.session_id}>
                <Link
                  href={ROUTES.chatSession(s.session_id)}
                  className="flex items-center justify-between py-2 text-sm hover:bg-brand-50"
                >
                  <span className="truncate">{s.session_title}</span>
                  <span className="ml-2 text-xs text-gray-400">
                    {new Date(s.update_at).toLocaleString("zh-CN", {
                      hour12: false,
                    })}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}
