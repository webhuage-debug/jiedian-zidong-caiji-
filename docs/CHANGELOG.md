# Changelog

## v0.2.0 - 2026-05-23

### Added

- 添加公开来源发现模块。
- 添加 GitHub 公开仓库候选文件发现。
- 添加公开 URL 种子采集配置 `PUBLIC_SOURCE_SEEDS`。
- 添加公开文本抓取、大小限制、请求超时、失败重试。
- 添加来源缓存、来源冷却、失败降频。
- 添加节点链接提取和协议识别，支持 `vmess`、`vless`、`trojan`、`ss`、`ssr`、`hysteria2`、`hy2`、`tuic`。
- 添加节点完全去重入库。
- 添加采集任务历史和来源级采集记录。
- 添加后台采集触发、来源缓存、采集历史的基础页面。

### Changed

- 仪表盘版本更新为 v0.2.0。
- 重写前端主入口，修复 Windows 环境下中文编码损坏导致的 JSX 风险。

## v0.1.0 - 2026-05-23

### Added

- 初始化项目基础结构。
- 添加 Fastify API、React 管理后台、SQLite schema。
- 添加管理员登录、退出、Session、修改密码接口。
- 添加登录失败限制和临时锁定。
- 添加 Docker Compose 部署骨架。
- 添加 README 和 docs 交接文档体系。
- 添加 `.env.example`、`.gitignore`、敏感文件检查脚本。
