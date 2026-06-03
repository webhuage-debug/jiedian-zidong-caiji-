# 节点控制台

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
- 实时查看当前仓库、请求 URL、活动请求数、目录页、候选文件、已抓文件、失败请求、解析节点、入库节点和过滤重复数量
- 调整验证线程数、数量、轮数和超时
- 启动与停止多线程验证
- 实时查看验证日志
- 分页浏览当前有效节点
- 实时查看累计过滤的重复节点数量
- 全自动控制：按分钟巡检有效节点库，低于阈值时优先验证节点库库存，节点库为空才采集补货
- 有效节点处理：导出时按模板临时改名，数据库原始节点不变
- 订阅链接管理：生成随机 token 的 Base64 订阅地址，支持按次数、按时间或任意条件达到后失效
- 受保护 Base64 订阅 API：`http://127.0.0.1:8765/adminhuage/api/subscription/base64`
- Telegram BOT 控制台：后台可保存 Token、关键字和测试回复内容，并启动独立轮询进程
- BOT 简单回复：用户消息完全匹配任意关键字后，立即发送后台配置的回复内容；YouTube 验证框架保留供后续接入
- BOT 自动运行：持久化开关保存到数据库；后台服务启动时按配置恢复 BOT，也可单独停止本次运行或关闭自动运行
