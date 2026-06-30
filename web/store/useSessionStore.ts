/**
 * 当前会话的轻量全局状态
 * 1 store = 1 职责：仅维护"当前选中的会话 ID + 标题"
 * 不要把会话列表/分页数据塞进来（用 TanStack Query 管理）
 */
import { create } from "zustand";

interface SessionState {
  currentSessionId: string | null;
  currentSessionTitle: string;
  setCurrent: (id: string | null, title?: string) => void;
  clear: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  currentSessionId: null,
  currentSessionTitle: "",
  setCurrent: (id, title = "") => set({ currentSessionId: id, currentSessionTitle: title }),
  clear: () => set({ currentSessionId: null, currentSessionTitle: "" }),
}));
