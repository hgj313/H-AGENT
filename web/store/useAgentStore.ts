/**
 * 当前 Agent 的轻量全局状态
 * 1 store = 1 职责：仅维护"当前选中的 Agent ID"
 */
import { create } from "zustand";

interface AgentState {
  currentAgentId: string | null;
  setCurrent: (id: string | null) => void;
}

export const useAgentStore = create<AgentState>((set) => ({
  currentAgentId: null,
  setCurrent: (id) => set({ currentAgentId: id }),
}));
