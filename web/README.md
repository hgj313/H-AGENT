# H-Agent Web（前端）

通用 Agent 平台前端 - Next.js 14 + TypeScript + TailwindCSS + Zustand + TanStack Query。

## 启动

```bash
# 在仓库根目录
cd web

# 安装依赖（推荐 pnpm）
pnpm install

# 启动开发服务器（端口 3000）
pnpm dev

# 类型检查
pnpm typecheck

# 跑单测
pnpm test

# 生产构建
pnpm build && pnpm start
```

## 与后端的联调

- 默认前端在 `http://localhost:3000`，后端在 `http://localhost:8000`
- 开发环境通过 `web/next.config.mjs` 的 `rewrites` 把 `/api/proxy/*` 转发到后端
- 生产环境建议同源或加网关

后端需先启动（在仓库根）：

```bash
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
```

## 目录结构

```
web/
├── app/                # Next.js App Router
│   ├── page.tsx        # Agent Hub（首页）
│   ├── agents/[id]/    # Agent 详情
│   ├── chat/           # 通用对话
│   └── design-review/  # 设计审查（3 页：配置 / 实时 / 报告）
├── components/         # 通用 UI + 业务组件
│   ├── common/         # Button / Card / Skeleton
│   ├── agent/          # AgentCard
│   └── layout/         # TopNav
├── hooks/              # useAgentList / useStreamChat / useDesignReviewSession
├── services/           # agentService / chatService / designReviewService
├── api/                # apiClient / sseClient
├── store/              # Zustand stores（useSessionStore / useAgentStore）
├── types/              # 严格对齐后端 schema
├── constants/          # routes / eventTypes
├── lib/                # utils
└── tests/              # vitest
```

## 架构约束

- **依赖方向**：`page → hook → service → api-client`，禁止跨层调用
- **状态管理**：本地用 `useState/useReducer`；跨页用 Zustand 严格 1 store = 1 职责
- **流式响应**：通过 `streamPostSSE()` 复用，统一处理 POST + SSE 协议
- **类型安全**：`tsconfig.json` 启用 `strict + noUncheckedIndexedAccess + noImplicitOverride`

## 当前阶段

- P1 骨架 ✅：脚手架 + types + API 层 + services + hooks + Zustand + 基础组件 + 首页可跑
- P2 待办：Agent 详情完善 + 历史会话
- P3 待办：通用对话页（消息流 + 工具调用卡 + 会话列表 inline 编辑）
- P4 待办：设计审查（3 页拆分 + 节点状态条 + 思考流 + 工具时间线 + 报告渲染 + 虚拟列表）
