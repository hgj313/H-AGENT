/**
 * useAgentActions - Agent 操作（pause/resume/restart）
 * 单一职责：调 agentService.action + 失效 Agent 相关缓存
 */
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { agentService } from "@/services/agentService";

type AgentAction = "pause" | "resume" | "restart";

export function useAgentActions() {
  const qc = useQueryClient();
  return useMutation<{ ok: boolean; agent_id: string; action: string }, Error, {
    agentId: string;
    action: AgentAction;
  }>({
    mutationFn: ({ agentId, action }) => agentService.action(agentId, action),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ["agents"] });
      void qc.invalidateQueries({ queryKey: ["agent", vars.agentId] });
    },
  });
}
