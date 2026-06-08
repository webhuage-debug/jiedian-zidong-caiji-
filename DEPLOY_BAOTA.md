# 宝塔面板部署说明

本文用于把项目部署到海外 VPS，并通过宝塔/Nginx 做反向代理。

## 固定端口

- Web 后台：`127.0.0.1:8765`
- Sub-Store sidecar：`127.0.0.1:3001`
- 后台路径：`/adminhuage`
- 健康检查：`http://127.0.0.1:8765/healthz`

不要把 `8765` 和 `3001` 直接暴露到公网，公网只通过宝塔/Nginx 反代访问后台域名。

## 1. 拉取代码

```bash
cd /www/wwwroot
git clone -b codex/v1.1.0-release https://github.com/webhuage-debug/jiedian-zidong-caiji-.git node.huage.us
cd /www/wwwroot/node.huage.us
```

如果要固定到 1.1.0 标签：

```bash
git checkout v1.1.0
```

## 2. 准备 Python 环境

建议 Python 3.11 或更高版本。

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. 下载 Xray Linux 内核

发布仓库不内置 Xray 二进制和 geo 数据文件，需要在 VPS 上按架构下载。

```bash
mkdir -p tools/xray
cd tools/xray
rm -f xray geoip.dat geosite.dat
```

x86_64 VPS：

```bash
curl -L -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip
```

ARM64 VPS：

```bash
curl -L -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-arm64-v8a.zip
```

解压并验证：

```bash
unzip -o /tmp/xray.zip xray geoip.dat geosite.dat -d .
chmod +x xray
./xray version
cd /www/wwwroot/node.huage.us
```

## 4. 启动 Sub-Store

推荐 Docker 部署时使用 `docker-compose.yml` 里的 `sub-store` sidecar。

如果你用宝塔 Python 项目方式部署主程序，也需要单独运行 Sub-Store。可以二选一：

### 方式 A：用 Docker 单独跑 Sub-Store

```bash
docker run -d \
  --name huage-sub-store \
  --restart unless-stopped \
  -p 127.0.0.1:3001:3001 \
  -v /www/wwwroot/node.huage.us/data/sub-store:/opt/app/data \
  xream/sub-store:latest
```

### 方式 B：用 docker compose 跑整套服务

```bash
cd /www/wwwroot/node.huage.us
docker compose up -d
```

Docker Compose 会启动：

- `huage-web`：Web 后台，端口 `8765`
- `huage-sub-store`：订阅转换 sidecar，端口 `3001`

## 5. 宝塔 Python 项目配置

如果不用 Docker 跑 Web，而是使用宝塔 Python 项目管理器：

| 项目 | 填写内容 |
| --- | --- |
| 项目名称 | `Huage-Free` |
| 项目路径 | `/www/wwwroot/node.huage.us` |
| 启动文件 | `web_app.py` |
| Python 环境 | `.venv` 或宝塔创建的 Python 3.11+ 环境 |
| 启动用户 | `www` |

环境变量建议：

```text
HUAGE_HOST=127.0.0.1
HUAGE_PORT=8765
HUAGE_ADMIN_BASE_PATH=/adminhuage
HUAGE_DATABASE=/www/wwwroot/node.huage.us/data/nodes.db
HUAGE_LOG_DIR=/www/wwwroot/node.huage.us/data/logs
HUAGE_SUB_STORE_URL=http://127.0.0.1:3001
```

## 6. 宝塔反向代理

在宝塔网站中添加反向代理：

```text
代理名称：node-dashboard
目标 URL：http://127.0.0.1:8765
发送域名：$host
```

Nginx 反代建议补充：

```nginx
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_buffering off;
proxy_read_timeout 3600s;
```

## 7. 启动后检查

```bash
curl http://127.0.0.1:8765/healthz
curl http://127.0.0.1:3001
```

后台地址：

```text
https://你的域名/adminhuage
```

默认后台账号：

```text
admin
admin888
```

首次登录后请立即修改密码，并在后台检查：

- Xray 当前版本是否可识别
- Sub-Store 健康检查是否通过
- 订阅转换是否能返回内容
- 总控是否按预期开启
- 系统维护清理策略是否启用

## 8. 数据和日志

以下目录是运行数据，不要提交到 Git：

- `data/nodes.db`
- `data/logs/`
- `data/reports/`
- `data/sub-store/`

正式运行前建议备份：

```bash
tar -czf huage-data-backup-$(date +%F).tar.gz data
```
