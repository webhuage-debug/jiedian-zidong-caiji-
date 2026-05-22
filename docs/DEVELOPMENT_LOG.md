# Development Log

## 2026-05-23

### 开发工具或 AI

- Codex

### 本次任务

- 开发 v0.1.0 项目基础版。

### 实现思路

- 使用单体部署形态降低 VPS 部署复杂度：Fastify 后端提供 API，同时托管 Vite 构建后的前端静态文件。
- 使用 SQLite 作为默认数据库，Docker volume 持久化 `/data`。
- 先建立后续版本需要的数据表，避免后续采集、测试、导出功能反复调整基础结构。
- 登录系统从第一阶段开始落地，避免后台裸奔。

### 遇到的问题

- 当前 Windows 环境中直接调用 `node.exe` 被拒绝访问。
- 当前环境没有 `npm`、`docker`、`gh` 命令。
- 当前 Git 仓库没有 remote。

### 解决方式

- 继续完成源码与部署文件。
- 使用 Codex bundled Node 路径执行无依赖敏感检查脚本。
- 用 PowerShell 补充扫描敏感文件名和 Token 模式。

### 未解决问题

- 尚未确认 GitHub 私有远程仓库地址。
- 尚未完成依赖安装和构建验证。
- 尚未完成 GitHub push。

### 后续建议

- v0.2.0 前先保证 GitHub 私有仓库可推送。
- v0.2.0 实现采集任务时必须先实现限速、缓存、失败降频，再增加来源发现。

## 2026-05-23 v0.2.0

### 开发工具或 AI

- Codex

### 本次任务

- 开发节点采集与解析版。

### 实现思路

- 采集入口先以 GitHub 公共仓库发现和管理员配置的公开 URL 种子为主。
- 所有采集都走来源缓存、冷却时间、并发限制、请求超时和大小限制。
- 第一版只提取节点链接和协议类型，不做深度字段解析。
- 节点使用内容 SHA-256 做完全去重。

### 遇到的问题

- v0.1.0 中部分中文 UI 文案在当前 Windows PowerShell 环境显示为乱码，前端 JSX 存在语法风险。
- 当前环境仍没有 `npm`、`docker`、`gh`。

### 解决方式

- 重写 `apps/api/src/routes.ts`，移除损坏文案。
- 重写 `apps/web/src/main.tsx`，先修复损坏 JSX，再恢复中文 UI 文案。
- 配置 GitHub remote：`https://github.com/webhuage-debug/jiandiancaiji.git`。

### 未解决问题

- 尚未在 Docker/Linux 环境真实运行采集。
- 尚未 push，需在本阶段提交后执行。

### 后续建议

- 在 VPS 或 Docker 环境执行 `npm install`、`npm run build` 和一次采集。
- v0.3.0 开始实现基础连通性测试与候选节点池。

## 2026-05-23 v0.3.0

### 开发工具或 AI

- Codex

### 本次任务

- 开发节点测试与候选池版。

### 实现思路

- 不启动代理服务，不开放端口，只从节点链接解析 host/port 后做出站 TCP 连接初筛。
- 测试通过写入 `test_passed` 和 `latency_ms`。
- 测试失败写入 `test_failed` 和 `failure_reason`，不进入候选池。
- 仪表盘展示测试批次、节点池预览和延迟分布。

### 遇到的问题

- 当前环境无法执行 npm/Docker 构建，也无法真实访问 GitHub 进行 push 或采集验证。

### 解决方式

- 使用源码级检查和敏感文件检查确认本阶段改动。
- 将网络/DNS 阻塞写入交接日志。

### 未解决问题

- 未在 Linux VPS 上执行真实 TCP 测试。
- 未执行 TypeScript 类型检查。

### 后续建议

- 在 VPS 环境完成 `npm install`、`npm run build`、采集和测试联调。
- v0.4.0 实现导出批次、纯节点文件和加密 zip 包。
