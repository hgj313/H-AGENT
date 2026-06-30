"use client";

import { AgentCard } from "@/components/agent/AgentCard";
import { Skeleton } from "@/components/common/Skeleton";
import { useAgentList } from "@/hooks/useAgentList";

export default function HomePage() {
  const { data, isLoading, isError, error, refetch } = useAgentList();

  return (
    <div>
      <header className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-brand-500">Agent 中心</h1>
          <p className="mt-1 text-sm text-gray-500">
            选择一个 Agent 开始对话或审查
          </p>
        </div>
      </header>

      {isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} variant="rect" />
          ))}
        </div>
      )}

      {isError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          加载失败：{error?.message ?? "未知错误"}
          <button
            type="button"
            onClick={() => refetch()}
            className="ml-2 underline hover:no-underline"
          >
            重试
          </button>
        </div>
      )}

      {data && data.agents.length === 0 && (
        <p className="text-sm text-gray-500">暂无可用 Agent</p>
      )}

      {data && data.agents.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.agents.map((agent) => (
            <AgentCard key={agent.config.agent_id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}
