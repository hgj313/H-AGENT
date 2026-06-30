/**
 * Agent 相关类型 - 严格对齐后端 core/agents/base.py + api/v1/schemas/agents.py
 */

export type AgentType =
  | "design_review"
  | "react"
  | "code_review"
  | "document"
  | "custom";

export type AgentStatus = "idle" | "running" | "paused" | "error" | "disabled";

export interface AgentConfigInfo {
  agent_id: string;
  name: string;
  description: string;
  agent_type: AgentType;
  version: string;
  capabilities: string[];
  max_concurrent: number;
  timeout: number;
  metadata?: Record<string, unknown>;
}

export interface AgentStateInfo {
  status: AgentStatus;
  current_task_id: string | null;
  error_count: number;
  last_error: string | null;
}

export interface AgentInfo {
  config: AgentConfigInfo;
  state: AgentStateInfo;
  is_available: boolean;
}

export interface AgentListResponse {
  total: number;
  agents: AgentInfo[];
}
