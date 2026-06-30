"use client";

import { useAgentActions } from "@/hooks/useAgentActions";
import { Button } from "@/components/common/Button";

export interface AgentActionButtonsProps {
  agentId: string;
  currentStatus: string;
}

/** Agent 操作按钮组：pause / resume / restart */
export function AgentActionButtons({ agentId, currentStatus }: AgentActionButtonsProps) {
  const action = useAgentActions();
  const pending = action.isPending;

  const run = async (act: "pause" | "resume" | "restart") => {
    try {
      await action.mutateAsync({ agentId, action: act });
    } catch {
      // 错误已通过 mutation 状态暴露
    }
  };

  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Agent 操作">
      {currentStatus === "running" ? (
        <Button
          variant="secondary"
          loading={pending}
          onClick={() => run("pause")}
        >
          暂停
        </Button>
      ) : (
        <Button
          variant="primary"
          loading={pending}
          onClick={() => run("resume")}
        >
          恢复
        </Button>
      )}
      <Button
        variant="ghost"
        loading={pending}
        onClick={() => run("restart")}
      >
        重启
      </Button>
      {action.isError && (
        <p role="alert" className="self-center text-xs text-red-600">
          {action.error?.message}
        </p>
      )}
    </div>
  );
}
