# Architecture

## 总体形态

Public Node Admin 是部署在 VPS 上的网页后台系统。v0.1.0 采用单体容器部署：

- Fastify 后端提供 REST API。
- React + Vite 构建管理后台。
- Fastify 在生产环境托管前端静态文件。
- SQLite 数据库保存在 Docker volume 的 `/data/app.db`。
- 后续导出的节点包保存在 `/data/exports`，不得提交到 GitHub。

## 后端结构

- `apps/api/src/server.ts`：应用入口，注册插件、API 和静态文件托管。
- `apps/api/src/config.ts`：环境变量解析。
- `apps/api/src/db.ts`：SQLite 连接和初始化。
- `apps/api/src/schema.ts`：数据库 schema。
- `apps/api/src/auth.ts`：管理员登录、Session、失败锁定、修改密码。
- `apps/api/src/routes.ts`：v0.1.0 基础业务 API。

## 前端结构

- `apps/web/src/main.tsx`：登录页、后台布局和 v0.1.0 仪表盘。
- `apps/web/src/styles.css`：响应式后台样式。
- `apps/web/vite.config.ts`：开发代理配置。

## 数据库结构

核心表：

- `admin_users`：管理员账号和密码哈希。
- `sessions`：后台登录 Session。
- `auth_failures`：登录失败次数和锁定状态。
- `node_sources`：公开节点来源记录。
- `nodes`：节点池。
- `collection_runs`：采集任务历史。
- `test_runs`：测试任务历史。
- `export_batches`：导出批次。
- `batch_stats`：领取页统计。
- `public_events`：领取页事件流水。
- `feedback`：外部用户反馈。
- `app_settings`：系统设置。
- `app_logs`：运行日志。

## 采集流程

v0.2.0 已实现基础采集框架：

1. 从允许的公开来源入口发现 URL。
2. 检查来源缓存和 `next_allowed_at`，避免高频访问。
3. 限制并发和请求超时。
4. 提取文本中的节点链接。
5. 识别协议类型。
6. 清洗、去重、入库。
7. 保存采集任务统计。

只采集公开内容，不访问私人仓库，不绕过登录，不做全网乱扫。

模块位置：

- `apps/api/src/collector/sourceDiscovery.ts`：公开来源发现。
- `apps/api/src/collector/http.ts`：受限 HTTP 抓取。
- `apps/api/src/collector/nodeParser.ts`：节点协议提取和哈希。
- `apps/api/src/collector/collectionService.ts`：采集运行、来源缓存、去重入库。

## 测试流程规划

v0.3.0 已实现基础测试框架：

1. 读取待测试或需要复测的节点。
2. 从节点链接中解析 host/port。
3. 对 host/port 做 TCP 连接初筛。
4. 记录字段“后台初筛延迟”。
5. 测试通过进入候选节点池。
6. 测试失败标记原因并从默认候选视图剔除。
7. 保存延迟分布和测试任务统计。

模块位置：

- `apps/api/src/tester/nodeEndpoint.ts`：节点 host/port 解析。
- `apps/api/src/tester/connectivity.ts`：TCP 连接测试。
- `apps/api/src/tester/testService.ts`：测试批次、节点状态、失败原因和延迟统计。

当前测试只判断节点地址是否明显不可连，不代表真实客户端使用延迟。

## 导出流程规划

v0.4.0 已实现：

1. 管理员设置批次名称、导出数量、延迟范围、排序方式、口令、有效期。
2. 默认筛选测试通过、未导出、延迟最低的节点。
3. 生成一行一个节点的纯文本文件，不附加备注。
4. 生成密码加密 zip 包。
5. 写入 `export_batches` 并标记节点所属批次。

模块位置：

- `apps/api/src/exporter/exportService.ts`：导出节点选择、批次创建、纯文本和 zip 包生成。
- `apps/api/src/routes.ts`：导出批次 API。
- `apps/web/src/main.tsx`：后台导出表单和批次列表。

当前 zip 加密依赖系统 `zip` 命令，Docker runtime 镜像已安装 `zip`。在本地 Windows 环境如果没有 zip 命令，导出动作会失败；生产部署目标是 Linux VPS。

## 领取页流程规划

v0.5.0 已实现：

1. 外部用户访问公开领取页。
2. 系统记录访问事件和来源平台参数。
3. 用户输入口令。
4. 口令正确后允许下载 zip 节点包。
5. 系统记录口令、解锁、下载和反馈统计。

模块位置：

- `apps/api/src/publicClaim.ts`：公开领取页 API、口令验证、下载、反馈和事件统计。
- `apps/web/src/main.tsx`：公开领取页前端。

领取页不会直接展示完整节点，只提供加密 zip 包下载。

## 统计流程规划

- 管理后台从 `collection_runs`、`test_runs`、`nodes`、`export_batches`、`batch_stats`、`feedback` 汇总仪表盘。
- 公开视频模式启用时，前后端都需要隐藏完整节点、账号、来源链接、Token、IP、UUID、密码和服务器信息。
