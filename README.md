# Public Node Admin

Public Node Admin 是一个部署在 Debian / Ubuntu VPS 上的个人自用网页后台系统，用来整理公开网络中的代理节点资源，并在后台完成采集、清洗、基础初筛、候选池管理、节点包导出和公开领取页管理。

当前版本：v0.1.0 项目基础版。

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

## 规划功能

- v0.2.0：公开来源发现、GitHub/网页/文本采集、节点协议识别、去重入库
- v0.3.0：基础连通性测试、后台初筛延迟、失败剔除、候选节点池、延迟分布
- v0.4.0：自定义数量导出、纯节点文件、加密 zip 节点包、批次管理
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
