# 节点控制台

> **开发必读：** 后续所有开发、调试、部署和提交必须先遵循 [00_DEVELOPMENT_RULES.md](00_DEVELOPMENT_RULES.md)。本项目当前在 Windows 开发，最终面向 Linux VPS + Docker + 7x24 自动化运行，端口必须固定。

使用 [Scrapling](https://github.com/D4Vinci/Scrapling) 网页爬虫从公开 GitHub 仓库中提取代理节点 URI 和疑似订阅链接。默认内置本项目需求中的 9 个仓库，不调用 GitHub API。

支持常见 URI：`vless`、`vmess`、`ss`、`ssr`、`trojan`、`hysteria`、`hysteria2`、`hy2`、`tuic`、`wireguard`、`wg`、`mieru`、`juicity`、`naive+https`、`socks` 和 `socks5`。

解析器会扫描常见文本、Mihomo/Clash YAML、Sing-box JSON、配置文件和无扩展名的疑似节点文件，并递归解析最多两层 Base64。结构化 `proxies` 和 `outbounds` 对象会转换为节点 URI。发现的疑似订阅链接会继续抓取并转换为节点。内网、本地和保留地址会被拒绝。节点会在发现后立即批量写入 SQLite 的 `节点库` 表，中途停止时已抓到的节点仍会保留。

## 使用

Scrapling 要求 Python 3.10 或更高版本。本工具使用它的静态 `Fetcher`，无需安装浏览器组件。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python node_collector.py
```

默认每次请求前等待 `1.0` 至 `1.5` 秒。可按需放慢速度：

```bash
.venv/bin/python node_collector.py --delay 2 --delay-jitter 1
```

默认使用 5 个受控并发线程抓取 Raw 文件，并最多使用 4 个线程解析订阅链接。目录页按顺序扫描，数据库统一由主线程持续写入。可调整采集线程数和日志粒度：

```bash
.venv/bin/python node_collector.py --workers 5 --log-level detail
```

日志粒度可选 `compact`、`detail` 和 `nodes`。`nodes` 会逐条显示节点 URI 以及新增入库或重复过滤结果。

持久化数据库位于 `data/nodes.db`：

- `节点库`：爬取到的全部去重节点、来源和验证状态
- `有效节点`：通过 Xray 稳定性验证的节点、耗时和出口 IP
- `系统统计`：累计记录采集过程中已过滤的重复节点数量

数据库是唯一的节点持久化来源。程序不会生成节点文本文件、CSV、JSONL 或日志文件。

查看数据库统计：

```bash
.venv/bin/python node_db_stats.py
```

可追加或替换仓库：

```bash
.venv/bin/python node_collector.py --repo owner/repo --repo another/repo
.venv/bin/python node_collector.py --repo-file repos.txt
```

工具只读取公开仓库文件，不会默认访问仓库内容中发现的任意外链。请仅在符合当地法律、仓库许可证和服务条款的场景中使用结果。

## Xray 验证

使用 `tools/xray/xray` 验证节点。默认从数据库的 `节点库` 表读取尚未验证的节点，开启 10 个并发验证任务，每次最多处理 50 条。每条结果会实时更新 `节点库` 的 `未验证`、`有效` 或 `无效` 状态。通过稳定检查的节点会同步写入 `有效节点` 表；重新验证失败时会从 `有效节点` 表移除。

```bash
.venv/bin/python node_validator.py
```

可调整并发数：

```bash
.venv/bin/python node_validator.py --workers 10
```

可调整稳定性检查轮数：

```bash
.venv/bin/python node_validator.py --rounds 3 --round-delay 0.75
```

随机抽取指定协议：

```bash
.venv/bin/python node_validator.py --protocol ss --protocol vless --random --limit 50
```

重新验证已分类节点：

```bash
.venv/bin/python node_validator.py --revalidate --random --limit 50
```

## Web 管理面板

启动本地 Web 服务：

```bash
.venv/bin/python web_app.py
```

浏览器打开：

```text
http://127.0.0.1:8765/adminhuage
```

初始后台账号：

```text
admin / admin888
```

面板支持：

- 后台登录验证，账号和会话保存到数据库
- 软件日志、数据库时间、会话时间和订阅过期时间统一使用北京时间（UTC+8）
- 启动采集和马上停止采集
- 调整采集线程数、请求延迟和日志粒度
- 采集源管理：支持维护 GitHub 仓库列表、单独启用/禁用仓库，并在启动采集时只使用已启用仓库
- 实时查看当前仓库、请求 URL、活动请求数、目录页、候选文件、已抓文件、失败请求、解析节点、入库节点和过滤重复数量
- 调整验证线程数、数量、轮数和超时
- 启动与停止多线程验证
- 定时复检有效节点：自动控制可按间隔复检有效节点，复检失败的节点会从有效节点库剔除
- Xray 调用验证：通过本地 Xray 启动 SOCKS 入站做连通性、延迟、出口 IP 和国家/地区识别；Linux 默认使用 `tools/xray/xray`，Windows 自动识别 `tools/xray/xray.exe`
- 实时查看验证日志
- 分页浏览当前有效节点
- 实时查看累计过滤的重复节点数量
- 全自动控制：按分钟巡检有效节点库，低于阈值时优先验证节点库库存，节点库为空才采集补货
- 总控调度：手动采集、手动验证、自动补齐和有效节点复检统一通过总控协调，采集与验证互斥运行，状态接口返回 `mode`、`intent`、`phase`、`decision` 和最近原因
- 订阅发放单一入口：有效节点处理页只负责命名模板、预览和原始节点导出；Base64/多格式订阅统一在“订阅链接管理”生成带随机 token、访问次数和过期时间的链接
- 订阅转换：轻量调用 Sub-Store 兼容 `/download/{profile}` 接口，支持手动选择输入协议类型并转换到 V2RayNG、Clash Verge、Sing-box、Surge、Shadowrocket，成功和失败都会写入转换日志
- Sub-Store 运行建议：生产/Docker 环境推荐把 Sub-Store 作为独立 sidecar 服务运行，主系统通过 `HUAGE_SUB_STORE_URL` 配置内网地址；后台提供健康检查按钮并记录检查日志
- Docker sidecar：已提供 `Dockerfile`、`docker-compose.yml` 和 `.env.example`。Compose 中主系统固定对外 `8765`，Sub-Store 固定映射 `3001:3001` 便于本地联调；主系统通过 `HUAGE_SUB_STORE_URL` 调用，Docker 内网示例值为 `http://sub-store:3001`
- 有效节点处理：按模板预览临时改名效果，数据库原始节点不变；只保留节点预览和原始节点导出，不直接生成订阅
- 订阅导出质量策略：默认每条订阅最多导出 100 条节点，按低延迟优先、亚洲节点加权和稳定性评分排序；亚洲候选不足时自动回退全球候选
- 订阅链接管理：生成随机 token 的 Base64 订阅地址，支持按次数、按时间或任意条件达到后失效，并可启用、禁用或删除
- 订阅转换：后台单独页面轻量调用 Sub-Store 兼容 `/download/{name}` 转换接口，不完整下载第三方仓库；支持 V2RayNG、Clash Verge、Sing-box、Surge 和 Shadowrocket 小火箭；输入可选有效节点池或手动粘贴订阅内容，并提供健康检查和转换日志
- 领取口令配置：后台可手动修改口令、版本、有效期和每日领取次数；版本变更后旧版本领取请求会失效；成功、口令错误、口令过期和超过次数文案均可配置
- 公开领取校验 API：`http://127.0.0.1:8765/api/claim-code/redeem`
- Telegram BOT 控制台：后台可保存 Token、关键字、群内提示、私聊领取说明、私发多格式订阅卡片模板和公开访问地址，并启动独立轮询进程
- YouTube 轻量验证引导：后台可配置 YouTube 频道链接、最新免费节点领取视频链接和引导文案；系统只引导用户订阅频道、观看最新视频并输入视频内口令，不调用 YouTube API 做强制订阅校验
- BOT 领取闭环：群组关键词触发后提示用户私聊；私聊发送 `/start` 或关键词会返回领取说明；私聊提交口令后按版本、有效期和每日次数验证，成功后自动生成随机 token 订阅链接并私发 V2RayNG、Clash Verge、Sing-box、Surge、Shadowrocket 小火箭订阅卡片
- BOT 自动运行：持久化开关保存到数据库；后台服务启动时按配置恢复 BOT，也可单独停止本次运行或关闭自动运行
## Sub-Store Sidecar

- Windows 本地调试：先运行 `start_substore_3001.cmd`，再打开后台订阅转换页检查健康状态。
- 本地 sidecar 使用官方 release 单文件 `tools/sub-store/sub-store.bundle.js`，固定监听 `3001`，数据写入 `data/sub-store`。
- 后台转换前会自动确认 Sub-Store 内存在 `sub` profile；缺失时自动创建，避免“未找到订阅：sub”导致转换失败。
- Docker/VPS 部署：使用 `docker-compose.yml` 中的 `sub-store` sidecar，主系统通过 `HUAGE_SUB_STORE_URL=http://sub-store:3001` 调用，外部固定端口仍为 `8765` 和 `3001`。

## 端到端真实验收

- 快速验收：`python e2e_acceptance_runner.py --smoke --skip-collect --skip-validate`
- 30 次/分钟领取压测：`python e2e_acceptance_runner.py --skip-collect --skip-validate --claim-rounds 30 --claim-rate-per-minute 30`
- 完整流程验收：`python e2e_acceptance_runner.py --collect-target 20000 --valid-target 100 --claim-rounds 30 --claim-rate-per-minute 30`
- 执行器只调用现有后台 API、BOT 模拟、公开订阅入口和 Sub-Store 转换接口；报告输出到 `data/reports`。
