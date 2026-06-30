/**
 * 路由常量 - 集中管理便于重构
 */
export const ROUTES = {
  agentHub: "/",
  agentDetail: (id: string) => `/agents/${encodeURIComponent(id)}`,
  chat: "/chat",
  chatSession: (id: string) => `/chat/session/${encodeURIComponent(id)}`,
  designReview: "/design-review",
  designReviewSession: (id: string) =>
    `/design-review/session/${encodeURIComponent(id)}`,
  designReviewReport: (id: string) =>
    `/design-review/report/${encodeURIComponent(id)}`,
} as const;

export type RouteKey = keyof typeof ROUTES;
