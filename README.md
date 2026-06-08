# 节点自动采集与订阅分发后台

这是一个用于 GitHub 仓库节点采集、Xray 验证、有效节点筛选、订阅转换、BOT 口令领取和后台自动化运维的管理系统。

> 开发、部署和后续修改必须先阅读 [00_DEVELOPMENT_RULES.md](00_DEVELOPMENT_RULES.md)。

## 主要能力

- GitHub 仓库采集源管理、启用/禁用、来源画像统计。
- 节点去重入库、待验证节点管理、无效节点剔除。
- Xray 连通性验证、延迟检测、出口 IP 检测、国家/地区识别。
- 有效节点低水位检测、自动补采、自动验证、定时复检。
- 亚洲优先、低延迟优先、稳定性评分、精品订阅池。
- 订阅链接 token、访问次数限制、过期时间限制、启用/禁用。
- Base64、V2RayNG、Clash Verge、Sing-box、Surge、Shadowrocket、Raw 导出。
- 轻量调用 Sub-Store sidecar 做订阅转换。
- 领取口令配置、口令版本、每日领取次数、提示文案配置。
- Telegram BOT 群组关键词触发、私聊口令验证、多格式订阅卡片。
- YouTube 频道/视频口令引导，不强制调用 YouTube API 校验。
- 真实验收任务、BOT 模拟、订阅真实性检测、系统维护清理。

## 固定端口

- Web 后台：`8765`
- Sub-Store sidecar：`3001`
- 后台路径：`/adminhuage`

后台地址：

```text
http://127.0.0.1:8765/adminhuage
```

默认账号：

```text
admin
admin888
```

首次登录后请立即修改密码。

## 本地运行

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python web_app.py
```

Windows PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe web_app.py
```

健康检查：

```bash
curl http://127.0.0.1:8765/healthz
```

## Docker 部署

推荐 VPS 使用 Docker Compose：

```bash
git clone -b codex/v1.1.0-release https://github.com/webhuage-debug/jiedian-zidong-caiji-.git huage-node
cd huage-node
docker compose up -d
```

Docker Compose 会启动：

- `huage-web`：Web 后台，映射 `8765:8765`
- `huage-sub-store`：Sub-Store sidecar，映射 `3001:3001`

运行数据挂载到：

```text
./data
```

## 宝塔部署

宝塔/Nginx 反代请看 [DEPLOY_BAOTA.md](DEPLOY_BAOTA.md)。

建议公网只暴露域名和 HTTPS，不直接暴露 `8765`、`3001`。

## Xray

发布仓库不内置 Xray 二进制、`geoip.dat`、`geosite.dat`。

Linux VPS 需要下载对应架构的 Xray 到：

```text
tools/xray/xray
tools/xray/geoip.dat
tools/xray/geosite.dat
```

后台 Xray 页面支持查看当前版本、拉取官方版本列表、下载和切换版本。

## Sub-Store

订阅转换通过 Sub-Store sidecar 完成。

Docker 环境默认地址：

```text
http://sub-store:3001
```

宝塔 Python 项目方式部署时，建议单独运行 Sub-Store 并配置：

```text
HUAGE_SUB_STORE_URL=http://127.0.0.1:3001
```

发布仓库不内置 `tools/sub-store/sub-store.bundle.js`，生产环境推荐直接使用 Docker sidecar。

## 真实验收

快速烟测：

```bash
python e2e_acceptance_runner.py --smoke --skip-collect --skip-validate
```

领取/订阅压测：

```bash
python e2e_acceptance_runner.py --skip-collect --skip-validate --claim-rounds 30 --claim-rate-per-minute 30
```

完整流程：

```bash
python e2e_acceptance_runner.py --collect-target 20000 --valid-target 100 --claim-rounds 30 --claim-rate-per-minute 30
```

验收报告写入：

```text
data/reports
```

## 测试

发布前建议运行：

```bash
python -m unittest discover -v
```

当前 `v1.1.0` 发布前已通过 90 个单元测试。

## 不应提交到 Git 的内容

- `.env`
- `.venv/`
- `data/`
- `build/`
- `__pycache__/`
- 运行日志
- SQLite 数据库
- Xray 二进制和 geo 数据
- Sub-Store bundle 和运行数据

这些内容已经写入 `.gitignore` 和 `.dockerignore`。

## 版本

当前发布版本：

```text
v1.1.0
```
