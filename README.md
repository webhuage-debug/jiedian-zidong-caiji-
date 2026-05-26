# Public Node Admin

Public Node Admin 是一个部署在 Debian / Ubuntu VPS 上的华哥自用节点采集、测试、订阅池维护后台。系统用于整理公开网络中的代理节点资源，完成采集、去重、基础初筛、Xray-core 真实检测、订阅活动创建、公开领取页口令验证、raw/base64 订阅输出、反馈统计和备用节点包导出。

当前版本：v1.1.0 自动节点订阅池版。

## 当前主流程

1. 后台自动采集公开节点并去重入库。
2. 后台执行基础 TCP 初筛。
3. Xray-core 低并发队列做真实代理检测。
4. 后台创建每期 YouTube 视频对应的订阅活动。
5. 粉丝打开公开领取页 `/r/:slug`。
6. 粉丝输入视频口令。
7. 口令正确后复制 raw / base64 订阅链接。
8. 订阅有效期内后台定时健康检查，只替换失效或明显劣化节点。
9. 订阅到期后返回中文提示，引导查看最新 YouTube 视频获取新订阅。

ZIP 节点包、nodes.txt、clash.yaml、sing-box.json 仍保留为后台备用导出能力，但不再作为粉丝公开领取页的主交付方式。

## 功能概览

- 管理员账号密码登录，密码 bcrypt 哈希存储。
- 登录失败限制、Session Cookie、退出登录、公开视频/录屏模式。
- GitHub 公开仓库、公开网页、公开文本、公开订阅 URL 采集。
- 支持提取 `vmess`、`vless`、`trojan`、`ss`、`ssr`、`hysteria2`、`hy2`、`tuic` 链接。
- 节点去重、来源缓存、采集限速、失败降频。
- 基础 TCP 初筛，记录后台初筛延迟。
- Xray-core 真实代理检测，默认低并发队列运行，只监听 `127.0.0.1`。
- 节点池显示基础延迟、真实代理延迟、协议、状态、来源和测试时间。
- 节点包备用导出，支持自定义数量、延迟范围、协议、质量档位。
- 订阅活动管理：活动名称、视频备注、开始时间、截止时间、视频口令、输出节点数量、健康阈值。
- raw / base64 通用订阅输出：`/sub/:token/raw`、`/sub/:token/base64`。
- 订阅缓存目录：默认 `/data/sub-cache`。
- 订阅健康检查：默认每 300 秒扫描应检查活动，只替换失效、超出淘汰延迟或真实检测过旧节点。
- 公开领取页只展示口令输入、订阅链接复制、基础说明和反馈入口。
- 反馈数据自动关联领取活动、订阅 token、来源渠道和设备/客户端信息。
- Telegram Bot 第一版只读接口：`GET /api/public/current-claim`，只返回当前领取页链接，不直接发订阅链接。
- 运行日志、统计数据、渠道统计、反馈处理和安全说明文档。

## 部署环境

优先支持：

- Ubuntu 22.04
- Ubuntu 24.04
- Debian 12
- Docker Engine
- Docker Compose Plugin

## 快速部署

```bash
git clone <private-repo-url>
cd public-node-admin
cp .env.example .env
nano .env
docker compose up -d --build
```

访问：

```text
http://你的服务器IP:3000
```

首次管理员账号由 `.env` 中的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 设置。数据库中已有管理员后，修改环境变量不会覆盖数据库里的密码。

## 关键配置

- `PUBLIC_BASE_URL`：当前服务公开基础地址。
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`：首次初始化管理员账号密码。
- `SESSION_SECRET`：Session Cookie 签名密钥，生产环境必须换成长随机字符串。
- `DATABASE_PATH`：SQLite 数据库路径。
- `EXPORT_DIR`：后台备用节点包导出目录。
- `SUB_CACHE_DIR`：订阅缓存目录，默认 `/data/sub-cache`。
- `SUBSCRIPTION_DEFAULT_DAYS`：订阅活动默认有效天数，建议 15。
- `SUBSCRIPTION_DEFAULT_OUTPUT_COUNT`：默认订阅输出节点数量，建议 10。
- `SUBSCRIPTION_CACHE_MAX_AGE_SECONDS`：订阅缓存与健康检查周期，建议 300。
- `XRAY_REAL_TEST_ENABLED`：是否启用 Xray-core 真实检测。
- `XRAY_CORE_PATH`：容器内 Xray-core 路径。
- `XRAY_REAL_TEST_CONCURRENCY`：Xray 真实检测并发，默认 2。
- `XRAY_REAL_TEST_TIMEOUT_SECONDS`：单节点真实检测超时，默认 12 秒。
- `DOWNLOAD_RATE_LIMIT_PER_MINUTE`：公开下载限速。
- `AUTOMATION_API_TOKEN`：只读自动化接口 Token，留空则禁用。

真实 `.env` 禁止提交 GitHub。

## 安全边界

- 后台必须登录后访问，不能裸奔。
- 公开领取页不显示后台入口、节点来源、测试细节、服务器信息、数据库路径或完整节点池。
- 订阅链接使用随机 token，不使用自增 ID。
- 订阅访问只读取缓存，不触发实时采集、实时 Xray 检测或全量筛选。
- Xray 临时代理只监听 `127.0.0.1`，不监听 `0.0.0.0`，不开放代理端口。
- 订阅缓存、数据库、节点包、日志、节点数据、Token、真实 `.env` 禁止提交 GitHub。
- 录屏模式下隐藏完整 token、slug、IP、节点链接、来源 URL、管理员账号和敏感日志。
- 免费节点存在时效性，不承诺 100% 可用、永久可用或所有地区/客户端都可用。

## 文档

- [交接日志](docs/HANDOFF.md)
- [开发日志](docs/DEVELOPMENT_LOG.md)
- [TODO](docs/TODO.md)
- [CHANGELOG](docs/CHANGELOG.md)
- [架构说明](docs/ARCHITECTURE.md)
- [部署说明](docs/DEPLOY.md)
- [安全说明](docs/SECURITY.md)
