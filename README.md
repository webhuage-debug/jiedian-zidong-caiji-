# Public Node Admin

Public Node Admin 是一个部署在 Debian / Ubuntu VPS 上的个人自用网页后台系统，用来整理公开网络中的代理节点资源，并在后台完成采集、清洗、基础初筛、候选池管理、节点包导出和公开领取页管理。

当前版本：v0.4.0 节点包导出版。

## 当前功能

- Fastify + TypeScript 后端基础结构
- React + Vite 管理后台基础页面
- SQLite 数据库初始化
- 管理员账号密码登录
- 密码 bcrypt 哈希存储，不明文保存
- HTTP Cookie Session 管理和过期时间
- 登录失败次数限制和临时锁定
- 退出登录
- 修改密码接口
- 公开视频模式前端开关雏形
- Docker Compose 部署骨架
- `.env.example` 配置模板
- `.gitignore` 和敏感文件检查脚本
- 多 AI 接力文档体系
- 公开来源发现和来源缓存
- GitHub 公开仓库候选文件发现
- 公开网页/文本/订阅 URL 种子采集
- 节点协议链接提取：`vmess`、`vless`、`trojan`、`ss`、`ssr`、`hysteria2`、`hy2`、`tuic`
- 完全相同节点去重并入库
- 采集限速、请求超时、大小限制、失败重试、失败降频
- 基础连通性测试：解析节点 host/port 后做 TCP 连接初筛
- 记录字段“后台初筛延迟”
- 测试失败节点不进入候选池
- 测试批次历史、失败原因和延迟分布
- 节点池支持协议、状态、来源、延迟区间、导出状态筛选的后端接口
- 自定义导出数量，默认 10 条，可手动改为 11、20、30 或任意合理数量
- 默认导出测试通过、未导出、后台初筛延迟最低的节点
- 生成纯节点文本文件，不追加延迟、来源、状态或备注
- 生成包含导入说明、使用说明、免责声明、反馈模板的 zip 节点包
- 管理员手动设置本期口令，口令同时用于 zip 包加密
- 导出批次记录：批次编号、状态、节点数量、领取页 slug、有效期

## 规划功能

- v0.5.0：公开领取页、口令验证、下载统计、反馈入口
- v0.6.0：完整公开视频模式、日志脱敏、下载限速、采集限速完善
- v1.0.0：第一版正式可用

## 部署环境

优先支持：

- Ubuntu 22.04
- Ubuntu 24.04
- Debian 12
- Docker Engine
- Docker Compose Plugin

## 快速启动

```bash
git clone <private-repo-url>
cd public-node-admin
cp .env.example .env
nano .env
docker compose up -d
```

访问：

```text
http://你的服务器IP:3000
```

首次管理员账号由 `.env` 中的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 设置。数据库中已有管理员后，重新修改环境变量不会覆盖数据库里的密码。

## 本地开发

```bash
npm install
npm run dev
```

后端默认监听 `3000`，前端 Vite 默认监听 `5173` 并代理 `/api` 到后端。

## 配置说明

关键环境变量：

- `ADMIN_USERNAME`：首次初始化管理员账号
- `ADMIN_PASSWORD`：首次初始化管理员密码
- `SESSION_SECRET`：Session Cookie 签名密钥，生产环境必须换成长随机字符串
- `DATABASE_PATH`：SQLite 数据库路径
- `EXPORT_DIR`：后续节点包导出目录
- `LOGIN_MAX_FAILURES`：登录失败锁定阈值
- `LOGIN_LOCK_MINUTES`：登录失败锁定时间
- `PUBLIC_SOURCE_SEEDS`：可选公开来源种子，多个 URL 用英文逗号分隔
- `COLLECT_MAX_CONCURRENCY`：采集并发上限
- `COLLECT_DAILY_MAX_RUNS`：每日最大采集次数
- `COLLECT_MIN_INTERVAL_MINUTES`：同一来源最小重复访问间隔
- `HTTP_TIMEOUT_SECONDS`：单次请求超时
- `TEST_CONNECT_TIMEOUT_SECONDS`：基础测试 TCP 连接超时
- `TEST_BATCH_SIZE`：单次默认测试节点数量

真实 `.env` 禁止提交到 GitHub。

## 安全注意事项

- 后台必须登录后访问
- 管理员密码只保存哈希
- 不提交数据库、日志、节点数据、节点包、真实配置、Token
- 生产环境必须替换默认管理员密码和 `SESSION_SECRET`
- 公开领取页后续只允许口令验证后下载加密节点包，不直接展示完整节点
- 采集功能后续必须限制频率、并发和失败重试

更详细说明见 [docs/SECURITY.md](docs/SECURITY.md)。

## 文档

- [交接日志](docs/HANDOFF.md)
- [开发日志](docs/DEVELOPMENT_LOG.md)
- [TODO](docs/TODO.md)
- [CHANGELOG](docs/CHANGELOG.md)
- [架构说明](docs/ARCHITECTURE.md)
- [部署说明](docs/DEPLOY.md)
- [安全说明](docs/SECURITY.md)
