# Deploy

## 支持系统

- Ubuntu 22.04
- Ubuntu 24.04
- Debian 12

## 安装 Docker

参考 Docker 官方文档安装 Docker Engine 和 Docker Compose Plugin。安装完成后确认：

```bash
docker version
docker compose version
```

## 部署项目

```bash
git clone <private-repo-url>
cd public-node-admin
cp .env.example .env
nano .env
docker compose up -d
```

生产环境必须修改：

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `SESSION_SECRET`
- `PUBLIC_BASE_URL`

## 访问后台

```text
http://服务器IP:3000
```

如果前面接入 Nginx、Caddy 或 Cloudflare，请把 `PUBLIC_BASE_URL` 设置为真实 HTTPS 地址。

## 数据目录

Docker volume `app-data` 挂载到容器内 `/data`：

- `/data/app.db`：SQLite 数据库
- `/data/exports`：后续节点包导出目录

这些运行数据不得提交到 GitHub。

## 常用命令

启动：

```bash
docker compose up -d
```

查看日志：

```bash
docker compose logs -f app
```

停止：

```bash
docker compose down
```

更新：

```bash
git pull
docker compose up -d --build
```

## 备份

```bash
docker compose down
docker run --rm -v public-node-admin_app-data:/data -v "$PWD:/backup" busybox tar czf /backup/app-data-backup.tgz /data
docker compose up -d
```

备份文件可能包含数据库、统计、节点包和敏感配置，不能上传到公开位置。

## 恢复

```bash
docker compose down
docker run --rm -v public-node-admin_app-data:/data -v "$PWD:/backup" busybox sh -c "cd / && tar xzf /backup/app-data-backup.tgz"
docker compose up -d
```
