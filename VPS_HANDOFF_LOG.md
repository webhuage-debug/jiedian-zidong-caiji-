# VPS 部署交接日志

交接日期：2026-06-07  
发布版本：`v1.0.0`  
远端仓库：`https://github.com/webhuage-debug/jiedian-zidong-caiji-.git`  
发布分支：`codex/v1.0.0-release`  
当前发布提交：`08f44d8`

## 1. 本次上传状态

本次已经完成：

- 清空旧 GitHub 仓库内容。
- 上传当前软件源码、前端、测试、文档和部署文件。
- 标记版本标签：`v1.0.0`。
- 修复 `docker-compose.yml`，不再强制依赖未上传的 `.env`。
- 重写可读中文文档：
  - `README.md`
  - `DEPLOY_BAOTA.md`
  - `00_DEVELOPMENT_RULES.md`
- 从 GitHub 重新克隆干净副本验证。
- 发布前全量测试通过：`82` 个单元测试通过。

## 2. 未上传内容

以下内容已故意排除，不应进入 Git：

- `data/`
- SQLite 数据库：`nodes.db`
- 运行日志
- 验收报告
- `build/`
- `__pycache__/`
- `.venv/`
- `.env`
- Xray 二进制：`tools/xray/xray`、`tools/xray/xray.exe`
- Xray 数据文件：`geoip.dat`、`geosite.dat`
- Sub-Store bundle 和运行数据

这些内容需要在 VPS 上重新生成、下载或通过 Docker sidecar 提供。

## 3. VPS 拉取命令

```bash
cd /www/wwwroot
git clone -b codex/v1.0.0-release https://github.com/webhuage-debug/jiedian-zidong-caiji-.git node.huage.us
cd /www/wwwroot/node.huage.us
git checkout v1.0.0
```

如果后续要跟随发布分支更新，可以不 checkout 标签，直接留在：

```bash
codex/v1.0.0-release
```

## 4. 推荐部署方式

优先推荐 Docker Compose：

```bash
cd /www/wwwroot/node.huage.us
docker compose up -d
```

该方式会启动：

- `huage-web`：Web 后台，端口 `8765`
- `huage-sub-store`：Sub-Store sidecar，端口 `3001`

数据挂载：

```text
/www/wwwroot/node.huage.us/data
```

如果使用宝塔 Python 项目方式，请参考：

```text
DEPLOY_BAOTA.md
```

## 5. Xray 必须单独准备

仓库不内置 Xray 二进制。VPS 上需要下载 Linux 版本。

x86_64：

```bash
mkdir -p tools/xray
cd tools/xray
curl -L -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip
unzip -o /tmp/xray.zip xray geoip.dat geosite.dat -d .
chmod +x xray
./xray version
```

ARM64：

```bash
mkdir -p tools/xray
cd tools/xray
curl -L -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-arm64-v8a.zip
unzip -o /tmp/xray.zip xray geoip.dat geosite.dat -d .
chmod +x xray
./xray version
```

## 6. Sub-Store 注意事项

Docker Compose 会自动启动 Sub-Store。

如果不用 Docker Compose，而是宝塔 Python 项目方式部署 Web，则需要单独启动 Sub-Store：

```bash
docker run -d \
  --name huage-sub-store \
  --restart unless-stopped \
  -p 127.0.0.1:3001:3001 \
  -v /www/wwwroot/node.huage.us/data/sub-store:/opt/app/data \
  xream/sub-store:latest
```

Web 环境变量应配置：

```text
HUAGE_SUB_STORE_URL=http://127.0.0.1:3001
```

Docker Compose 内部默认使用：

```text
HUAGE_SUB_STORE_URL=http://sub-store:3001
```

## 7. 宝塔反向代理

公网不要直接暴露 `8765` 和 `3001`。

宝塔网站反代目标：

```text
http://127.0.0.1:8765
```

后台访问路径：

```text
https://你的域名/adminhuage
```

建议 Nginx 增加：

```nginx
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_buffering off;
proxy_read_timeout 3600s;
```

## 8. 首次启动后检查

健康检查：

```bash
curl http://127.0.0.1:8765/healthz
curl http://127.0.0.1:3001
```

后台登录：

```text
admin
admin888
```

首次登录后必须修改密码。

后台重点检查：

- Xray 当前版本是否识别。
- Xray 能否下载官方版本。
- Sub-Store 健康检查是否通过。
- 订阅转换是否能返回内容。
- 总控是否按预期开启。
- 系统维护清理策略是否启用。
- 采集、验证、订阅、BOT 模拟是否能跑通。

## 9. VPS 真实验收建议

先跑烟测：

```bash
python e2e_acceptance_runner.py --smoke --skip-collect --skip-validate
```

再跑领取和订阅转换压测：

```bash
python e2e_acceptance_runner.py --skip-collect --skip-validate --claim-rounds 30 --claim-rate-per-minute 30
```

最后跑完整流程：

```bash
python e2e_acceptance_runner.py --collect-target 20000 --valid-target 100 --claim-rounds 30 --claim-rate-per-minute 30
```

重点观察：

- 有效节点是否增长。
- 失败原因分布。
- 订阅是否真实导出节点。
- Clash Verge / Sing-box / V2RayNG 是否能正常导入。
- 数据库体积是否稳定。
- 日志是否按系统维护策略清理。

## 10. 已知注意事项

1. 本地 Windows 验证结果不能完全代表海外 VPS。
   VPS 的出口网络、DNS、机房环境会影响节点有效率。

2. 当前仓库不包含运行数据库。
   VPS 首次运行会创建新的 `data/nodes.db`。

3. 当前仓库不包含 Xray 内核。
   必须在 VPS 上下载 Linux 对应版本。

4. 当前仓库不包含 Sub-Store bundle。
   生产推荐 Docker sidecar，不推荐把第三方 bundle 提交进源码仓库。

5. 如果用宝塔 Python 项目部署，需要确保 Sub-Store 也在本机 `3001` 运行。

6. 如果 24 小时运行发现有效节点增长异常，不能直接定性为源差，需要同时审计验证逻辑、探测 URL、超时、协议解析和 VPS 网络环境。

## 11. 回滚方式

如果新版本不可用，可以先停止服务：

```bash
docker compose down
```

或在宝塔里停止 Python 项目。

保留数据目录：

```bash
tar -czf huage-data-backup-$(date +%F-%H%M).tar.gz data
```

回到指定标签：

```bash
git fetch --tags
git checkout v1.0.0
```

重新启动：

```bash
docker compose up -d
```

## 12. 后续更科学的发布流程

建议下一阶段改为：

- `main`：稳定分支
- `dev`：开发分支
- `release/v1.0.x`：发布分支
- GitHub Actions 自动测试
- GitHub Release 发布版本说明
- Docker 镜像打标签，例如 `huage-node:1.0.0`
- VPS 只拉稳定 release 或 Docker 镜像，不直接在 VPS 上改代码

当前 `v1.0.0` 建议作为 VPS 预生产测试版本，先跑 24 小时真实验收，再根据结果发布 `v1.0.1`。
