# Deploy

## VPS 一键部署

私有仓库推荐使用 GitHub fine-grained token 或 classic PAT，只授予该私有仓库读取权限。不要把 Token 写入 `.env`，不要提交到 GitHub。

在 Ubuntu 22.04 / Ubuntu 24.04 / Debian 12 VPS 上执行：

```bash
export GITHUB_TOKEN='替换为只读 GitHub Token'
export ADMIN_USERNAME='admin'
export ADMIN_PASSWORD='替换为强密码'
export PUBLIC_BASE_URL='http://你的服务器IP:3000'
bash -c "$(curl -fsSL -H "Authorization: Bearer ${GITHUB_TOKEN}" https://raw.githubusercontent.com/webhuage-debug/jiandiancaiji/codex/v1.0.0-release/scripts/deploy-vps.sh)"
```

如果不设置 `ADMIN_PASSWORD`，脚本会自动生成一个随机密码并在终端输出一次。

如果已经手动 clone 到 VPS：

```bash
cd /opt/public-node-admin
sudo bash scripts/deploy-vps.sh
```

脚本会自动安装 Docker、clone 或更新仓库、生成 `.env`、执行 `docker compose up -d --build`。

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

如果直接用 `http://服务器IP:3000` 访问，保持 `SESSION_COOKIE_SECURE=auto` 即可，系统会自动允许 HTTP Cookie。  
如果前面接入 HTTPS 反代或域名，`PUBLIC_BASE_URL` 使用 `https://...`，系统会自动启用 Secure Cookie。

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
