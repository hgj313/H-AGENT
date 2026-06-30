/**
 * Agent 服务 - 业务逻辑封装层
 *
 * 职责：组合 apiClient，向上提供业务语义化的方法
 * 禁止：直接被 React 组件/页面调用（必须经 hook）
 */

import { apiRequest } from "@/api/apiClient";
import type { AgentInfo, AgentListResponse } from "@/types/agent";

export const agentService = {
  /** 获取全部 Agent（Agent Hub 主页用） */
  list: (): Promise<AgentListResponse> =>
    apiRequest<AgentListResponse>("/api/v1/agents"),

  /** 获取单个 Agent 详情 */
  get: (agentId: string): Promise<AgentInfo> =>
    apiRequest<AgentInfo>(`/api/v1/agents/${encodeURIComponent(agentId)}`),

  /** 暂停/恢复/重启 Agent */
  action: (
    agentId: string,
    action: "pause" | "resume" | "restart",
  ): Promise<{ ok: boolean; agent_id: string; action: string }> =>
    apiRequest(`/api/v1/agents/${encodeURIComponent(agentId)}/actions`, {
      method: "POST",
      body: { action },
    }),
};
