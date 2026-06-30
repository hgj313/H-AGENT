/**
 * useAgentList - 通过 TanStack Query 拉取 Agent 列表
 * 单一职责：Agent Hub 页面用
 */
"use client";

import { useQuery } from "@tanstack/react-query";
import { agentService } from "@/services/agentService";
import type { AgentListResponse } from "@/types/agent";

export function useAgentList() {
  return useQuery<AgentListResponse, Error>({
    queryKey: ["agents", "list"],
    queryFn: () => agentService.list(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}
