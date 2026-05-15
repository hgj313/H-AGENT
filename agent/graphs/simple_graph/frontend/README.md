# Simple Graph Frontend

该目录作为独立前端工程承载 simple graph 演示页面。

当前实现采用零构建静态前端，便于直接由 FastAPI 挂载并演示以下能力：

- 创建独立用户会话
- 启动图执行
- 实时订阅流式事件
- 暂停/继续 interrupt
- 动态修改输入
- 加载快照并回滚

如需继续工程化，可在该目录下替换为 React/Vue 等独立前端项目，接口仍可直接复用 `/api/sessions/*`。
