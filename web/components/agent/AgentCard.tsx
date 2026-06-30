import Link from "next/link";
import { Card } from "@/components/common/Card";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/constants/routes";
import type { AgentInfo } from "@/types/agent";

const STATUS_DOT: Record<AgentInfo["state"]["status"], string> = {
  idle: "bg-status-pending",
  running: "bg-status-running animate-pulse",
  paused: "bg-yellow-500",
  error: "bg-status-error",
  disabled: "bg-gray-400",
};

const STATUS_LABEL: Record<AgentInfo["state"]["status"], string> = {
  idle: "空闲",
  running: "运行中",
  paused: "已暂停",
  error: "错误",
  disabled: "已禁用",
};

export interface AgentCardProps {
  agent: AgentInfo;
}

export function AgentCard({ agent }: AgentCardProps) {
  const { config, state, is_available } = agent;
  return (
    <Link
      href={ROUTES.agentDetail(config.agent_id)}
      className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 rounded-lg"
    >
      <Card>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-base font-semibold text-brand-500">
              {config.name}
            </h3>
            <p className="mt-1 line-clamp-2 text-sm text-gray-500">
              {config.description}
            </p>
          </div>
          <span
            className={cn(
              "inline-block h-2.5 w-2.5 shrink-0 rounded-full",
              STATUS_DOT[state.status],
            )}
            aria-label={STATUS_LABEL[state.status]}
            title={STATUS_LABEL[state.status]}
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {config.capabilities.slice(0, 3).map((cap) => (
            <span
              key={cap}
              className="rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-500"
            >
              {cap}
            </span>
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-gray-400">
          <span>v{config.version}</span>
          <span>
            {is_available ? "可用" : "不可用"} · {state.error_count} 错
          </span>
        </div>
      </Card>
    </Link>
  );
}
