# 宝塔面板部署说明

## 目录与访问地址

- 项目目录：`/www/wwwroot/node.huage.us`
- 后台监听：`127.0.0.1:8765`
- 后台地址：`https://node.huage.us/adminhuage`
- 健康检查：`http://127.0.0.1:8765/healthz`

服务默认只监听本机回环地址，不需要将 `8765` 端口暴露到公网。

## VPS 基础准备

在宝塔终端中执行：

```bash
cd /www/wwwroot/node.huage.us
python3 --version
uname -m
curl --version
```

建议使用 Python 3.11 或更高版本。节点验证依赖系统命令 `curl`。

上传包不包含本地 macOS Xray 内核。请根据 `uname -m` 输出下载 Linux 版本：

```bash
cd /www/wwwroot/node.huage.us/tools/xray
rm -f xray

# x86_64 VPS
curl -L -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip

# ARM64 VPS 使用下面这一行替换上一行
# curl -L -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-arm64-v8a.zip

unzip -o /tmp/xray.zip xray geoip.dat geosite.dat -d .
chmod +x xray
./xray version

cd /www/wwwroot/node.huage.us
chown -R www:www .
```

## 添加 Python 项目

在宝塔 Python 项目管理器中填写：

| 项目 | 填写内容 |
| --- | --- |
| 项目名称 | `Huage-Free` |
| Python 环境 | 选择 Python 3.11 或更高版本 |
| 启动方式 | `命令行启动` |
| 项目路径 | `/www/wwwroot/node.huage.us` |
| 启动命令 | `web_app.py` |
| 环境变量 | `无` |
| 启动用户 | `www` |
| 安装依赖包 | `/www/wwwroot/node.huage.us/requirements.txt` |

默认配置已经满足宝塔反代：

- `HUAGE_HOST=127.0.0.1`
- `HUAGE_PORT=8765`
- `HUAGE_ADMIN_BASE_PATH=/adminhuage`

## 反向代理

在宝塔网站 `node.huage.us` 中添加反向代理：

```text
代理名称：node-dashboard
目标 URL：http://127.0.0.1:8765
发送域名：$host
```

实时日志使用 SSE。若日志流无法持续刷新，在 Nginx 反代配置中补充：

```nginx
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_buffering off;
proxy_read_timeout 3600s;
```

## 启动后检查

在 VPS 终端中执行：

```bash
curl http://127.0.0.1:8765/healthz
```

正常结果类似：

```json
{"ok":true,"tasks":{"collector":false,"validator":false,"bot":false}}
```

然后访问：

```text
https://node.huage.us/adminhuage
```

首次登录账号：

```text
admin
admin888
```

登录后立即修改密码。

## BOT 自动运行

BOT 是否随后台恢复运行由数据库中的开关决定：

1. 进入后台 `BOT 机器人` 页面。
2. 填写 Telegram Bot Token。
3. 开启 `自动运行 BOT`。
4. 点击 `保存 BOT 配置`。

后台服务下次重启时会读取数据库配置并自动恢复 BOT。
