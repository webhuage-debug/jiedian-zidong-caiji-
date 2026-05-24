# Handoff Log

## 2026-05-24 Xray 全量队列检测补丁

- 本次目标：修复 Xray-core 真实检测只跑固定 50 条的问题，改为每批 50 条、低并发、自动持续检测未检测候选节点。
- 已完成：`POST /api/xray-test-runs` 会持续读取未做过 Xray 真实检测的候选节点，每批按设置数量执行，默认 50 条，直到未检测候选节点完成或收到暂停/停止请求。
- 已完成：`GET /api/xray-test-runs/stats` 返回全量候选统计，包括候选总数、已真实检测、未检测、真实可用、真实失败、平均真实延迟、0-100 / 100-200 / 200-300 / 300ms 以上档位数量和队列运行状态。
- 已完成：`POST /api/xray-test-runs/pause` 与 `POST /api/xray-test-runs/stop`。暂停/停止会在当前批次结束后生效，已完成结果保留。
- 已完成：后台“测试记录”页面增加 Xray 队列进度、全量统计、检测范围、每批数量、协议和延迟区间筛选，以及开始全量真实检测、暂停检测、继续检测、停止检测按钮。
- 安全边界：Xray 临时代理仍只监听 `127.0.0.1`，并发仍受 `XRAY_REAL_TEST_CONCURRENCY` 控制，单节点超时仍受 `XRAY_REAL_TEST_TIMEOUT_SECONDS` 控制。
- 注意：暂停和停止不是强杀正在检测的单个节点，而是在当前批次完成后生效，避免破坏正在清理的临时 Xray 进程。

## 2026-05-24 Xray-core 真检测补齐与发布前复测接口
### 本次目标
- 接上已完成的质量分档、标准节点包、自动化接口和发布草稿机制，不重复重构 UI。
- 把 `POST /api/xray-test-runs` 从“安全脚手架”升级为真正的 Xray-core 代理检测流程。
- 补齐节点包发布前复测/检查接口，方便发布前查看通过率、风险等级、最近测试时间和平均延迟。
### 本次完成
- `apps/api/src/tester/xrayService.ts` 已实现真实检测流程：读取基础测试通过节点，转换 VLESS / VMess / Trojan / Shadowsocks 为临时 Xray 配置，启动临时 Xray 进程，通过本地 HTTP 代理访问测试地址，记录真实代理延迟。
- Xray 临时入站只监听 `127.0.0.1`，使用 `XRAY_LOCAL_PORT_MIN` / `XRAY_LOCAL_PORT_MAX` 范围内随机端口，不监听 `0.0.0.0`，不对公网开放代理端口。
- 每个节点测试都有 `XRAY_REAL_TEST_TIMEOUT_SECONDS` 超时；测试结束后会关闭 Xray，必要时强制结束，并删除临时配置目录。
- 并发仍由 `XRAY_REAL_TEST_CONCURRENCY` 控制，配置上限为 5，默认 2，避免轻量 VPS 负载失控。
- 成功节点写入 `real_status=real_passed`、`real_latency_ms`、`quality_tier`、`test_method=xray-core`、`eligible_for_package=1`。
- 失败节点写入 `real_status=real_failed` 和脱敏失败原因，并设为不可进入高质量包；未配置 Xray 或协议暂不支持时只记录状态，不误伤原有 TCP 候选资格。
- 当前 Xray 第一阶段支持：VLESS、VMess、Trojan、Shadowsocks；Hysteria2、TUIC、sing-box 专属格式继续留给后续 sing-box 扩展。
- `XRAY_TEST_URL` 默认改为 `http://www.gstatic.com/generate_204`，同时代码支持 HTTPS CONNECT 测试地址。
- 新增 `POST /api/export-batches/:id/preflight`：对已生成批次做发布前检查，返回节点数、真实检测数量、通过率、平均延迟、质量档位、风险等级和提示。该检查是可选，不强制阻止发布。
### 修改文件
- `.env.example`
- `apps/api/src/config.ts`
- `apps/api/src/tester/xrayService.ts`
- `apps/api/src/exporter/exportService.ts`
- `apps/api/src/routes.ts`
- `docs/HANDOFF.md`
- `docs/DEVELOPMENT_LOG.md`
- `docs/TODO.md`
- `docs/SECURITY.md`
### 验证结果
- 本地 Windows 环境没有可用 `npm` 命令，系统 `node.exe` 也被当前环境拒绝执行；因此本地无法完成 TypeScript typecheck / build。
- 已进行代码级检查，确认没有把完整节点链接、Token、数据库、节点包或运行数据写入新增逻辑。
- 需要在 VPS Docker 环境执行：`docker compose up -d --build`，再配置 `XRAY_REAL_TEST_ENABLED=true` 和 `XRAY_CORE_PATH=/usr/local/bin/xray` 后实测 `POST /api/xray-test-runs`。
### 当前遗留
- `clash.yaml` 和 `sing-box.json` 仍是安全模板，主导入文件仍为 `nodes.txt`；完整协议转换可后续继续做。
- 质量档位阈值当前为默认规则，后续可做成后台可编辑配置。
### Git 状态
- 本次为用户要求的本地补齐工作，尚未提交、尚未 push。用户确认后再整体提交 GitHub。

## 2026-05-24 第二阶段能力补齐：质量档位、自动化接口、Xray 检测骨架

### 本次目标
- 先检查现有实现，保留已完成的中文 UI、采集、基础测试、导出、草稿发布、公开领取和反馈处理。
- 补齐第二阶段缺口：节点质量档位、节点包权限字段、标准节点包文件、Hermes/OpenClaw 只读自动化接口、Xray-core 真实检测安全骨架。

### 已确认已完成
- 节点包生成默认 `draft`，手动发布后才可领取。
- 发布新批次会替换旧 `published` 批次。
- 公开领取页使用 `/r/:slug`，公开 API 使用 `/api/public/claim/:slug`。
- 公开领取页保持极简，不显示后台包列表和节点来源。
- 渠道统计、反馈入口、反馈处理状态已具备基础闭环。

### 本次补齐
- `nodes` 增加真实检测与质量字段：真实代理延迟、真实状态、测试方式、成功/失败次数、质量档位、是否可入包。
- `export_batches` 增加质量档位和权限字段：是否需要口令、是否允许公开领取、是否允许自动化调用、是否允许 Hermes 读取文件/链接。
- 节点包新增标准文件：`nodes.txt`、`clash.yaml`、`sing-box.json`、`README.txt`。其中 `nodes.txt` 仍是主格式，保持纯节点内容。
- 导出支持质量档位、协议筛选、基础/真实延迟区间、只选真实检测通过节点、是否需要口令、自动化读取权限。
- 新增 Xray-core 真实检测入口：`POST /api/xray-test-runs`。
- Xray-core 检测默认关闭，必须配置 `XRAY_REAL_TEST_ENABLED=true` 和 `XRAY_CORE_PATH`；默认低并发，避免 VPS 负载失控。
- 新增只读自动化接口：
  - `GET /api/automation/packages`
  - `GET /api/automation/current-package`
  - `GET /api/automation/channel-links`
  - `GET /api/automation/daily-summary`
  - `GET /api/automation/stats-summary`
  - `GET /api/automation/packages/:id/download`
- 自动化接口必须带 `AUTOMATION_API_TOKEN`，未配置时默认禁用。
- 0-100ms 高质量包默认不进入自动化读取，除非后台手动开启自动化权限。
- 前端新增“自动化接口”页面；测试页新增 “Xray 真实检测”按钮；节点包页新增档位和权限设置。

### 安全说明
- Xray-core 当前以安全骨架接入：默认关闭，未配置内核时只记录跳过，不启动进程。
- 后续真实协议转换需要继续完善临时 Xray 配置生成、127.0.0.1 随机端口监听、代理访问测试和进程清理。
- 自动化接口只返回允许自动化读取的已发布包，不返回完整节点池、后台路径、Token 或数据库信息。

### 测试与检查
- 本地 Windows 环境缺少 `npm`，无法执行完整构建。
- 需要在 VPS Docker 环境执行构建和端到端验证。

### Git 状态
- 按用户要求暂未提交、暂未推送。
- 用户确认后再整体提交 GitHub。

## 2026-05-24 中文化、反馈处理与录屏安全补齐

### 本次目标
- 不重复改动已完成的采集、测试、导出和领取架构，只补齐后台中文化与反馈闭环的缺口。
- 让“反馈数据”页面可以实际处理粉丝反馈，而不是只展示记录。
- 继续保持生成节点包默认草稿、手动发布、公开领取页极简和录屏模式脱敏方向。

### 已完成
- 新增后台反馈处理接口：`PATCH /api/feedback/:id`。
- 反馈处理状态支持：未处理、已查看、已解决、无效反馈、需要重新生成节点包。
- 反馈数据页新增操作按钮：已查看、已解决、需重做包。
- 更新反馈表格布局，保留渠道、批次、设备、软件、问题类型、处理状态和备注。
- `docs/TODO.md` 已将反馈处理接口从待办改为 VPS 验证项。

### 修改文件
- `apps/api/src/routes.ts`
- `apps/web/src/main.tsx`
- `apps/web/src/styles.css`
- `docs/TODO.md`
- `docs/HANDOFF.md`

### 测试与检查
- 当前本地环境没有可用 `npm` 命令，无法在本地执行完整 `npm run build`。
- 下一步需要在 VPS 或有 Node/npm 的环境执行 Docker 构建验证。

### Git 状态
- 本次按用户要求只做本地修改，未提交、未推送。
- 用户确认后再整体提交 GitHub。

## 2026-05-24 节点包发布机制与公开领取端分离

### 本次目标
- 将“生成节点包”和“公开发布节点包”彻底分离。
- 生成节点包默认变为草稿，避免误触生成多个包影响粉丝领取。
- 新增 `/r/:slug` 极简公开领取页入口和 `/api/public/claim/:slug` 公开 API。
- 后台保留采集、测试、导出、节点包生成能力，不改 X-UI，不动 80/443，不改端口。

### 已完成
- `export_batches` 增加发布限制字段：`max_downloads`、`ip_download_limit`、`wrong_passphrase_limit`。
- 新增 `export_batch_nodes` 关联表：草稿只记录批次与节点关系，不再把节点立即标记为已导出。
- `createExportBatch` 固定生成 `draft`，即使前端传 `publish` 也不会自动公开。
- 新增后台接口：
  - `POST /api/export-batches/:id/publish`
  - `POST /api/export-batches/:id/close`
  - `DELETE /api/export-batches/:id`
  - `GET /api/stats/channels`
- 发布新批次时，旧 `published` 批次自动变为 `replaced`。
- 只有 `published` 且未过期批次能被公开领取。
- 公开领取接口改为：
  - `GET /api/public/claim/:slug`
  - `POST /api/public/claim/:slug/verify`
  - `GET /api/public/claim/:slug/download`
  - `POST /api/public/claim/:slug/feedback`
- 公开接口只返回标题、说明、有效期、解锁状态，不返回节点数量、后台路径、文件路径、统计、内部批次详情。
- 下载接口验证发布状态、有效期、口令解锁、总下载次数、单 IP 下载次数、文件路径边界。
- 公开领取页路径支持 `/r/:slug`，旧 `/p/:slug` 前端兼容进入同一领取页。
- 公开领取页和公开 API 增加 noindex 相关处理。
- 后台节点包页增加草稿、当前发布批次、历史批次分组，以及发布、关闭、删除草稿、复制链接。
- 统计页增加渠道来源统计，支持 `?from=youtube`、`?from=telegram` 等参数聚合。

### 待验证
- 本地尚未执行 Docker 构建。
- 需要 VPS 更新后验证：登录、生成草稿、发布批次、旧批次 replaced、公开 `/r/:slug` 口令验证、下载限制、关闭后不可下载。

## 2026-05-24 后台中文化、反馈入口与录屏语义补强

### 本次目标
- 不重复重构已有发布分离逻辑，只补齐后台中文展示、反馈入口、渠道统计、设置和日志页面语义。

### 已完成
- 前端新增统一状态映射：任务状态、节点状态、批次状态、失败原因、反馈问题类型、处理状态统一中文化。
- 测试记录批次展示改为“第 N 批”，状态不再直接显示 `completed`。
- 失效节点状态和失败原因改为中文，例如 `test_failed` → “测试不通过”，`timeout` → “连接超时”。
- 节点包管理批次主展示改为创建时间，不再把内部随机编号作为主字段。
- 统计数据页以渠道来源为核心，展示访问、口令输入、下载、反馈、问题率和转化率。
- 公开领取页下载后显示轻量反馈入口：“能用 / 不能用”、设备系统、客户端软件、问题类型和备注。
- 反馈接口新增 `issue_type`、`source_platform`、`process_status`、`process_note` 字段，自动关联批次和 from 渠道。
- 反馈数据页改为“节点使用反馈分析”，用于查看渠道、批次、设备、软件、问题类型、处理状态。
- 系统设置页补充基础设置、管理员设置、安全设置、采集设置、测试设置、节点包设置、领取页设置、备份恢复等分区说明。
- 运行日志页改为中文日志级别和更明确的空状态说明。



## 2026-05-24 节点包文件名乱码修复

### 问题
- 用户在 Windows 解压节点包后，包内中文文件名显示为乱码。
- 检查 `apps/api/src/exporter/exportService.ts` 后发现导出模板里的中文字符串也出现编码污染。

### 修复
- 将节点包内部文件名改为跨平台 ASCII：
  - `nodes.txt`
  - `v2rayN-guide.txt`
  - `usage.txt`
  - `disclaimer.txt`
  - `feedback-template.txt`
- 保持 `nodes.txt` 为纯节点文件，一行一个节点，不追加延迟、来源、备注或后台日志。
- 恢复说明文件内容为正常中文。
- 说明文件明确提示：后台初筛延迟不等于真实客户端使用延迟。

### 验证建议
- VPS 拉取更新并重建后，重新生成一个新节点包。
- 下载后在 Windows 解压，确认文件名不乱码。
- 打开 `nodes.txt`，确认里面只有纯节点内容。


## 2026-05-23 菜单栏与领取页入口修复

### 本次开发目标
- 修复后台左侧菜单点击无反应的问题。
- 修复节点包生成后领取页只有路径文本、不方便进入的问题。
- 保持当前阶段只做可用性修复，不继续做额外 UI 美化调整。

### 已完成
- `apps/web/src/main.tsx`：后台左侧菜单现在会切换首页、节点池、采集任务、测试记录、失效记录、节点包、领取页、统计、反馈、设置、日志等页面。
- `apps/web/src/main.tsx`：节点包批次列表新增“打开领取页”链接，点击后进入 `/p/{public_slug}` 公开领取页。
- `apps/web/src/main.tsx`：领取页保留口令验证、下载加密 zip 节点包、反馈提交功能。
- `apps/web/src/main.tsx`：统一后台和领取页 API 请求使用 `credentials: "same-origin"`，避免浏览器 Cookie 未携带导致按钮看起来无响应。
- `apps/web/src/main.tsx`：公开领取页已移除节点数量、内部批次编号等后台信息，只保留标题、说明、口令、下载和反馈。
- `apps/web/src/main.tsx`：补齐系统日志、统计数据、反馈数据的后台展示入口。
- `apps/web/src/styles.css`：仅补充菜单图标、筛选控件、领取页链接、统计/日志表格所需的最小样式。
- 已合并远程 `docs/ui-reference/`，并查看参考图：左侧固定菜单、浅色背景、白色卡片、绿色主色、清晰表格。
- `apps/web/src/styles.css` 已按参考图做最小代价调整：白色侧栏、绿色选中菜单、浅底白卡、表格行距和按钮状态更明显。

### 给 VPS 的更新方式
在 `/opt/public-node-admin` 目录执行：

```bash
git pull --ff-only origin codex/v1.0.0-release
grep -q '^TEST_MAX_CONCURRENCY=' .env || echo 'TEST_MAX_CONCURRENCY=20' >> .env
docker compose up -d --build
```

更新后浏览器强制刷新后台页面。生成节点包后，在“节点包管理”或“领取页管理”里点击“打开领取页”。完整领取地址格式为：

```text
http://你的域名:3000/p/批次slug
```

例如截图里的路径 `/p/Xy8sMnQ8Xt1gdwUH`，完整地址就是 `http://jd.huage.us:3000/p/Xy8sMnQ8Xt1gdwUH`。

### 测试记录
- 已执行 `node scripts/check-sensitive.mjs`，结果通过：`Sensitive file check passed for 41 tracked or pending files.`
- 已执行 UTF-8/乱码扫描，`apps/web/src/main.tsx`、`apps/web/src/styles.css`、`docs/HANDOFF.md` 均为 `utf8-ok`。
- 已执行 `git diff --check`，没有发现空白错误。
- 本地环境没有可用 `npm` 命令，无法在 Windows 本地执行 `npm run build`。
- 当前没有 VPS SSH 会话和后台真实密码，尚未执行 Docker 日志、curl 登录、浏览器点击等 VPS 端验证；需要用户通过 SSH 工具提供临时验证结果或允许远程登录后继续。

### GitHub / 分支状态
- 本地修复提交：`4ed016e fix: make node testing responsive`
- 本地修复提交：`fb5cece fix: wire admin navigation and claim links`
- 已合并远程新增参考图提交：`be615c0`、`6d0a89d`、`40c1ca1`
- 后续需要 push 到 `origin/codex/v1.0.0-release` 后，VPS 才能拉取这些修复。

### 敏感信息检查
- 本次修复未提交 `.env`、数据库、节点文件、节点包、运行日志或真实口令。
- 用户截图中曾出现后台密码信息，后续建议在 VPS 上自行修改管理员密码。

## 2026-05-23 按钮点击无明显反馈修复

### 问题

- 用户反馈后台“开始测试”等按钮点击后仍像没反应。
- 代码检查发现基础测试接口一次测试 100 条节点，但实现是串行 TCP 测试。
- 如果大量节点超时，每条最多 5 秒，100 条可能等待很久，前端直到接口返回才刷新，因此表现为“没反应”。

### 修复

- 新增 `TEST_MAX_CONCURRENCY`，默认 20。
- 基础测试服务改为并发批量测试，避免 100 条节点串行等待。
- 前端点击“开始测试”后立即显示“基础测试已开始...”提示。
- 前端点击“生成节点包”后立即显示“正在生成节点包...”提示。
- 导出前如果未填写本期口令，前端直接提示原因。

### 部署更新建议

- VPS 上拉取最新代码后执行：`docker compose up -d --build`。
- 如 `.env` 已存在，可追加：`TEST_MAX_CONCURRENCY=20`。
- 更新后再点击“开始测试”，应该更快看到测试结果。

## 2026-05-23 VPS 登录/界面无反应修复

### 问题

- 用户反馈安装到 VPS 后操作界面没有反应。
- 代码检查发现生产环境 Cookie 使用 `secure: config.isProduction`。
- Docker 部署默认 `NODE_ENV=production`，如果通过 `http://服务器IP:3000` 访问，浏览器不会保存/发送 Secure Cookie。
- 结果表现为登录、公开视频模式、领取页解锁等依赖 Cookie 的操作看起来没有反应。

### 修复

- 新增环境变量 `SESSION_COOKIE_SECURE=auto|true|false`。
- 默认 `auto`，当 `PUBLIC_BASE_URL` 以 `https://` 开头时启用 Secure Cookie；HTTP 直连 VPS 时关闭 Secure Cookie。
- 后台登录 Cookie 和公开领取页解锁 Cookie 都改用 `config.COOKIE_SECURE`。
- `.env.example` 和 `scripts/deploy-vps.sh` 已写入 `SESSION_COOKIE_SECURE=auto`。
- `README.md` 和 `docs/DEPLOY.md` 已补充说明。

### 部署更新建议

- VPS 上拉取最新代码后执行：`docker compose up -d --build`。
- 如果仍使用 HTTP 直连，确认 `.env` 中 `PUBLIC_BASE_URL=http://服务器IP:3000`，并设置或保留 `SESSION_COOKIE_SECURE=auto`。
- 如果使用 HTTPS 域名，设置 `PUBLIC_BASE_URL=https://你的域名`。

### Git 状态

- 已提交：`fix: support http vps cookie sessions`
- 已 push 到 GitHub 分支：`codex/v1.0.0-release`
- 最新用途：给 VPS 更新部署，解决 HTTP 访问时 Cookie 不保存导致的登录/按钮无反应问题。

### 给后续 AI 的备注

- 用户会让 Claude 参与接手，请始终先读本文件最新章节。
- 用户要求：关键阶段完成后必须及时更新交接日志并 push 到 GitHub。
- 当前仓库本地配置了 Git 代理 `http://127.0.0.1:7897`，用于访问 GitHub。

## 2026-05-23 v1.0.0

### 本次开发时间

- 2026-05-23 Asia/Shanghai

### 本次开发目标

- 第一版正式可用版收口：系统需要能部署在 Debian / Ubuntu VPS，能通过浏览器登录后台，能采集公开节点、识别协议、去重、基础测试、候选池、延迟分布、自定义导出数量、加密节点包、公开领取页、访问/口令/下载/反馈统计、公开视频模式和完整文档交接。

### 已完成功能

- 应用版本更新为 v1.0.0。
- 新增后台批次统计接口：`GET /api/stats/batches`。
- 新增后台反馈数据接口：`GET /api/feedback`。
- 新增发布检查清单 `docs/RELEASE_CHECKLIST.md`。
- 新增 VPS 一键部署脚本 `scripts/deploy-vps.sh`。
- `docs/DEPLOY.md` 和 `README.md` 已加入一键部署命令。
- README 更新为 v1.0.0 正式版说明。

### 修改文件

- 修改 `package.json`
- 修改 `apps/api/package.json`
- 修改 `apps/api/src/routes.ts`
- 修改 `apps/web/package.json`
- 修改 `apps/web/src/main.tsx`
- 修改 `README.md`
- 修改 `docs/CHANGELOG.md`
- 修改 `docs/DEVELOPMENT_LOG.md`
- 修改 `docs/HANDOFF.md`
- 修改 `docs/TODO.md`
- 新增 `docs/RELEASE_CHECKLIST.md`
- 新增 `scripts/deploy-vps.sh`

### 删除文件

- 无

### 运行测试

- 已执行：`node scripts/check-sensitive.mjs`，使用 Codex bundled Node 路径执行。
- 已执行：UTF-8 内容扫描，确认 `apps/api/src/routes.ts`、`apps/web/src/main.tsx`、`README.md`、`docs/HANDOFF.md`、`docs/RELEASE_CHECKLIST.md` 无替换字符和明显乱码片段。
- 未执行：`npm install`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run typecheck`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run build`，当前环境没有可用 `npm` 命令。
- 未执行：Docker 构建和端到端验收，当前环境不是目标 Linux VPS，且缺少依赖安装。

### 测试结果

- 敏感文件检查通过：`Sensitive file check passed for 40 tracked or pending files.`
- UTF-8 扫描通过：核心后端、前端和文档文件未发现替换字符或明显乱码片段。
- 因本地环境缺少 `npm` 和 `docker`，依赖安装、类型检查、构建和端到端验收需在 VPS 或 Docker 环境继续验证。

### 当前问题

- 当前环境无法执行 npm/Docker 构建验证。
- 当前环境无法解析 `github.com`。
- 按用户要求，本阶段不主动 push GitHub。

### 下一步建议

- 在 VPS / Docker 环境执行 `docs/RELEASE_CHECKLIST.md`。
- 一键部署优先使用 `scripts/deploy-vps.sh`；私有仓库场景需要通过 `GITHUB_TOKEN` 读取 raw 脚本和 clone 仓库。
- 用户明确指令后，再统一 push GitHub。

### 敏感信息检查

- 本阶段不包含真实 `.env`、Token、数据库、节点包、运行日志。
- 运行数据目录、数据库、日志、节点包仍由 `.gitignore` 保护。

### Git commit 信息

- 本阶段提交信息计划：`chore: finalize v1.0.0 release`

### 是否已 push 到 GitHub

- 已按用户明确指令 push。执行一次性推送所有阶段分支：
- `git push -u origin codex/v0.1.0-foundation codex/v0.2.0-collector codex/v0.3.0-testing codex/v0.4.0-export codex/v0.5.0-public-claim codex/v0.6.0-security-video codex/v1.0.0-release`
- push 成功，GitHub 仓库：`https://github.com/webhuage-debug/jiandiancaiji.git`。
- 本地为当前仓库配置了 Git 代理：`http.proxy` 和 `https.proxy` 均为 `http://127.0.0.1:7897`。

### 备注

- 用户要求后续 VPS 需要一键部署，已新增 `scripts/deploy-vps.sh`。
- 推荐 VPS 一键部署命令见 `docs/DEPLOY.md` 的“VPS 一键部署”章节。
- 部署脚本会安装 Docker、clone/update 仓库、生成 `.env`、执行 `docker compose up -d --build`。
- 不要把 GitHub Token、真实 `.env`、节点包、数据库或日志提交到仓库。

## 2026-05-23 v0.6.0

### 本次开发时间

- 2026-05-23 Asia/Shanghai

### 本次开发目标

- 完成公开视频模式、隐藏完整节点、隐藏管理员账号、隐藏 IP / UUID / 密码 / Token / 来源链接、日志脱敏、下载限速、采集限速完善、敏感文件检查、SECURITY.md 完善。

### 已完成功能

- 新增后端设置模块 `apps/api/src/settings.ts`。
- 新增脱敏工具 `apps/api/src/security/redact.ts`。
- 公开视频模式保存到 `app_settings.public_video_mode`。
- 前端 公开视频模式 开关读写后端设置。
- 公开视频模式下前端隐藏管理员账号。
- 公开视频模式下节点池接口隐藏来源 URL，并脱敏失败原因。
- 公开视频模式下来源缓存接口隐藏来源 URL，并脱敏错误信息。
- 公开视频模式下日志接口脱敏节点链接、Token、UUID 和完整 IPv4。
- 公开下载接口增加按批次和 IP 哈希的分钟级限速。
- `.env.example` 新增 `DOWNLOAD_RATE_LIMIT_PER_MINUTE`。

### 修改文件

- 修改 `.env.example`
- 修改 `package.json`
- 修改 `apps/api/package.json`
- 修改 `apps/api/src/config.ts`
- 修改 `apps/api/src/publicClaim.ts`
- 修改 `apps/api/src/routes.ts`
- 修改 `apps/web/package.json`
- 修改 `apps/web/src/main.tsx`
- 修改 `README.md`
- 修改 `docs/ARCHITECTURE.md`
- 修改 `docs/CHANGELOG.md`
- 修改 `docs/DEVELOPMENT_LOG.md`
- 修改 `docs/HANDOFF.md`
- 修改 `docs/SECURITY.md`
- 修改 `docs/TODO.md`
- 新增 `apps/api/src/settings.ts`
- 新增 `apps/api/src/security/redact.ts`

### 删除文件

- 无

### 运行测试

- 已执行：`node scripts/check-sensitive.mjs`，使用 Codex bundled Node 路径执行。
- 已执行：UTF-8 内容扫描，确认 `apps/api/src/routes.ts`、`apps/api/src/publicClaim.ts`、`apps/api/src/security/redact.ts`、`apps/api/src/settings.ts`、`apps/web/src/main.tsx`、`README.md`、`docs/HANDOFF.md`、`docs/SECURITY.md` 无替换字符和明显乱码片段。
- 未执行：`npm install`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run typecheck`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run build`，当前环境没有可用 `npm` 命令。
- 未执行：下载限速端到端验证，当前环境不是目标 Linux VPS，且缺少依赖安装。

### 测试结果

- 敏感文件检查通过：`Sensitive file check passed for 39 tracked or pending files.`
- UTF-8 扫描通过：核心后端、前端和文档文件未发现替换字符或明显乱码片段。
- 因本地环境缺少 `npm` 和 `docker`，依赖安装、类型检查、构建和下载限速端到端验证需在 VPS 或 Docker 环境继续验证。

### 当前问题

- 当前环境无法执行 npm/Docker 构建验证。
- 当前环境无法解析 `github.com`。
- 按用户要求，本阶段不主动 push GitHub。

### 下一步建议

- v1.0.0 做最终端到端整合、部署验证、文档校正和安全验收。

### 敏感信息检查

- 本阶段不包含真实 `.env`、Token、数据库、节点包、运行日志。
- 公开视频模式和日志接口增加了基础脱敏，但仍建议 v1.0.0 做一次全页面录屏安全复查。

### Git commit 信息

- 本阶段提交信息：`feat: add v0.6.0 security video mode`

### 是否已 push 到 GitHub

- 未 push。用户明确要求：本地上传 GitHub 必须确认后或有明确指令后执行。本阶段只做本地 commit，等待用户后续统一推送指令。

## 2026-05-23 v0.5.0

### 本次开发时间

- 2026-05-23 Asia/Shanghai

### 本次开发目标

- 完成公开领取页、批次说明展示、口令输入、口令验证、正确口令后下载节点包、下载次数统计、访问次数统计、口令正确 / 错误次数统计、来源平台参数统计、简单反馈入口。

### 已完成功能

- 新增公开领取页前端 `/p/:slug`。
- 新增公开批次信息 API：`GET /api/public/batches/:slug`。
- 新增口令验证 API：`POST /api/public/batches/:slug/verify`。
- 新增节点包下载 API：`GET /api/public/batches/:slug/download`。
- 新增反馈 API：`POST /api/public/batches/:slug/feedback`。
- 口令正确后设置短时 HttpOnly 解锁 Cookie。
- 下载 API 必须先通过口令验证。
- 记录访问、口令尝试、口令正确、口令错误、解锁、下载、反馈统计。
- 支持 `?from=...` 来源平台参数记录。
- IP 使用 HMAC 哈希记录，不保存明文 IP。
- 公开领取页不直接展示完整节点。

### 修改文件

- 修改 `package.json`
- 修改 `apps/api/package.json`
- 修改 `apps/api/src/routes.ts`
- 修改 `apps/api/src/server.ts`
- 修改 `apps/web/package.json`
- 修改 `apps/web/src/main.tsx`
- 修改 `apps/web/src/styles.css`
- 新增 `apps/api/src/publicClaim.ts`
- 修改 `docs/CHANGELOG.md`
- 修改 `docs/DEVELOPMENT_LOG.md`
- 修改 `docs/HANDOFF.md`

### 删除文件

- 无

### 运行测试

- 已执行：`node scripts/check-sensitive.mjs`，使用 Codex bundled Node 路径执行。
- 已执行：UTF-8 内容扫描，确认 `apps/web/src/main.tsx`、`apps/api/src/publicClaim.ts`、`apps/api/src/routes.ts`、`README.md`、`docs/HANDOFF.md`、`docs/ARCHITECTURE.md`、`docs/SECURITY.md` 无替换字符和明显乱码片段。
- 未执行：`npm install`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run typecheck`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run build`，当前环境没有可用 `npm` 命令。
- 未执行：公开领取页下载端到端验证，当前环境不是目标 Linux VPS，且缺少依赖安装。

### 测试结果

- 敏感文件检查通过：`Sensitive file check passed for 37 tracked or pending files.`
- UTF-8 扫描通过：核心前端、公开领取 API、路由和文档文件未发现替换字符或明显乱码片段。
- 因本地环境缺少 `npm` 和 `docker`，依赖安装、类型检查、构建和公开领取页端到端验证需在 VPS 或 Docker 环境继续验证。

### 当前问题

- 当前环境无法执行 npm/Docker 构建验证。
- 当前环境无法解析 `github.com`。
- 按用户要求，本阶段不主动 push GitHub。

### 下一步建议

- v0.6.0 实现完整公开视频模式、日志脱敏、下载限速、采集限速完善和敏感信息隐藏。
- 在 VPS 上完成一次公开领取页口令验证和下载测试。

### 敏感信息检查

- 本阶段不包含真实 `.env`、Token、数据库、节点包、运行日志。
- 公开领取页不展示完整节点。

### Git commit 信息

- 本阶段提交信息：`feat: add v0.5.0 public claim page`

### 是否已 push 到 GitHub

- 未 push。用户明确要求：本地上传 GitHub 必须确认后或有明确指令后执行。本阶段只做本地 commit，等待用户后续统一推送指令。

## 2026-05-23 v0.4.0

### 本次开发时间

- 2026-05-23 Asia/Shanghai

### 本次开发目标

- 完成自定义导出数量，默认导出 10 条，支持修改为 11 / 20 / 30 / 自定义数量。完成按延迟最低优先导出、按延迟范围导出、默认优先导出未导出节点、生成纯节点 txt 文件、生成 zip 节点包、手动设置口令、zip 密码加密、批次管理、草稿 / 已发布状态。

### 已完成功能

- 新增导出服务 `apps/api/src/exporter/exportService.ts`。
- 支持导出数量默认 10 条，并可自定义。
- 支持最大/最小延迟筛选。
- 默认只导出 `test_passed` 节点。
- 默认排除已导出节点。
- 默认按后台初筛延迟从低到高导出。
- 生成纯节点文件 `候选节点.txt`，每行一个节点，不添加备注。
- 生成 `v2rayN导入说明.txt`、`使用说明.txt`、`免责声明.txt`、`反馈模板.txt`。
- 使用管理员手动输入的口令创建 zip 包。
- 口令使用 bcrypt 哈希保存。
- 创建 `export_batches` 批次记录和 `batch_stats` 初始记录。
- 导出后节点状态更新为 `exported`，记录 `exported_at` 和 `export_batch_id`。
- 后台新增节点包导出表单和批次列表。
- Docker runtime 镜像安装 `zip` 命令。

### 修改文件

- 修改 `package.json`
- 修改 `Dockerfile`
- 修改 `apps/api/package.json`
- 修改 `apps/api/src/db.ts`
- 修改 `apps/api/src/routes.ts`
- 修改 `apps/api/src/schema.ts`
- 修改 `apps/web/package.json`
- 修改 `apps/web/src/main.tsx`
- 修改 `apps/web/src/styles.css`
- 修改 `README.md`
- 修改 `docs/ARCHITECTURE.md`
- 修改 `docs/CHANGELOG.md`
- 修改 `docs/DEVELOPMENT_LOG.md`
- 修改 `docs/HANDOFF.md`
- 修改 `docs/SECURITY.md`
- 修改 `docs/TODO.md`
- 新增 `apps/api/src/exporter/exportService.ts`

### 删除文件

- 无

### 运行测试

- 已执行：`node scripts/check-sensitive.mjs`，使用 Codex bundled Node 路径执行。
- 已执行：UTF-8 内容扫描，确认 `apps/web/src/main.tsx`、`apps/api/src/routes.ts`、`apps/api/src/exporter/exportService.ts`、`README.md`、`docs/HANDOFF.md` 无替换字符和明显乱码片段。
- 未执行：`npm install`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run typecheck`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run build`，当前环境没有可用 `npm` 命令。
- 未执行：真实 zip 导出，当前环境不是目标 Linux VPS，且缺少依赖安装。

### 测试结果

- 敏感文件检查通过：`Sensitive file check passed for 36 tracked or pending files.`
- UTF-8 扫描通过：核心前端、后端导出服务、路由和文档文件未发现替换字符或明显乱码片段。
- 因本地环境缺少 `npm` 和 `docker`，依赖安装、类型检查、构建和真实 zip 导出需在 VPS 或 Docker 环境继续验证。

### 当前问题

- 当前环境无法执行 npm/Docker 构建验证。
- 当前环境无法解析 `github.com`，push 仍受阻。
- zip 加密依赖系统 `zip` 命令，已在 Docker runtime 安装，但尚未在 Linux 环境验证。

### 下一步建议

- v0.5.0 实现公开领取页、口令验证、下载节点包、访问/口令/下载统计和反馈入口。
- 在 VPS 上完成一次端到端采集、测试、导出验证。

### 敏感信息检查

- 本阶段不包含真实 `.env`、Token、数据库、节点包、运行日志。
- 导出的节点包只会在运行时写入 `/data/exports`，不会提交 GitHub。
- 口令不保存明文，只保存哈希。

### Git commit 信息

- 已本地提交：`c9ed031 feat: add v0.4.0 export batches`

### 是否已 push 到 GitHub

- 未 push 成功。执行 `git push -u origin codex/v0.4.0-export` 失败：`Could not resolve host: github.com`。
- 需要在网络/DNS 可访问 GitHub 的环境重试 push。

## 2026-05-23 v0.3.0

### 本次开发时间

- 2026-05-23 Asia/Shanghai

### 本次开发目标

- 完成基础连通性测试、基础延迟显示、测试失败剔除、失败原因记录、测试记录、候选节点池、节点状态管理、测试结果统计、延迟分布统计、按延迟排序、按协议/状态/延迟区间筛选。

### 已完成功能

- 添加节点 host/port 解析模块。
- 添加出站 TCP 基础连通性测试。
- 记录“后台初筛延迟”，不声称是真实使用延迟。
- 测试通过节点状态更新为 `test_passed`。
- 测试失败节点状态更新为 `test_failed`，记录失败原因，不进入候选池。
- 新增 `node_test_results` 表保存节点级测试结果。
- 新增测试任务 API：`GET /api/test-runs`、`POST /api/test-runs`。
- 仪表盘显示测试任务、节点池预览和延迟分布。
- 节点列表接口支持协议、状态、来源类型、延迟范围、是否已导出筛选。

### 修改文件

- 修改 `package.json`
- 修改 `.env.example`
- 修改 `apps/api/package.json`
- 修改 `apps/api/src/config.ts`
- 修改 `apps/api/src/routes.ts`
- 修改 `apps/api/src/schema.ts`
- 修改 `apps/web/package.json`
- 修改 `apps/web/src/main.tsx`
- 修改 `apps/web/src/styles.css`
- 修改 `README.md`
- 修改 `docs/ARCHITECTURE.md`
- 修改 `docs/CHANGELOG.md`
- 修改 `docs/DEVELOPMENT_LOG.md`
- 修改 `docs/HANDOFF.md`
- 修改 `docs/SECURITY.md`
- 修改 `docs/TODO.md`
- 新增 `apps/api/src/tester/nodeEndpoint.ts`
- 新增 `apps/api/src/tester/connectivity.ts`
- 新增 `apps/api/src/tester/testService.ts`

### 删除文件

- 无

### 运行测试

- 已执行：`node scripts/check-sensitive.mjs`，使用 Codex bundled Node 路径执行。
- 已执行：UTF-8 内容扫描，确认 `apps/web/src/main.tsx`、`apps/api/src/routes.ts`、`README.md`、`docs/HANDOFF.md` 无替换字符和明显乱码片段。
- 未执行：`npm install`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run typecheck`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run build`，当前环境没有可用 `npm` 命令。
- 未执行：真实 TCP 测试，当前环境不是目标 Linux VPS，且缺少依赖安装。

### 测试结果

- 敏感文件检查通过：`Sensitive file check passed for 35 tracked or pending files.`
- UTF-8 扫描通过：核心前端、后端路由和文档文件未发现替换字符或明显乱码片段。
- 因本地环境缺少 `npm` 和 `docker`，依赖安装、类型检查、构建和真实 TCP 测试需在 VPS 或 Docker 环境继续验证。

### 当前问题

- 当前环境无法执行 npm/Docker 构建验证。
- 当前环境无法解析 `github.com`，push 仍受阻。
- 基础测试只是 TCP 初筛，不代表真实客户端可用性或真实使用延迟。

### 下一步建议

- v0.4.0 实现节点导出数量自定义、纯节点文件、加密 zip 节点包和批次管理。
- 在 VPS 上完成一次端到端采集加测试验证。

### 敏感信息检查

- 本阶段不包含真实 `.env`、Token、数据库、节点包、运行日志。
- 测试结果和节点数据只写入运行数据库，不提交到 GitHub。

### Git commit 信息

- 已本地提交：`5140755 feat: add v0.3.0 node testing`

### 是否已 push 到 GitHub

- 未 push 成功。执行 `git push -u origin codex/v0.3.0-testing` 失败：`Could not resolve host: github.com`。
- 需要在网络/DNS 可访问 GitHub 的环境重试 push。

## 2026-05-23 v0.2.0

### 本次开发时间

- 2026-05-23 Asia/Shanghai

### 本次开发目标

- 完成公开节点来源搜索、GitHub 公开内容采集、公开网页/文本采集、节点协议识别、基础去重、节点入库、来源记录、采集日志、采集限速、失败重试、来源缓存。

### 已完成功能

- 添加 GitHub 公共仓库搜索和候选文件发现。
- 支持 `PUBLIC_SOURCE_SEEDS` 配置公开网页、文本、订阅 URL 种子。
- 添加受限 HTTP 抓取，支持超时和最大字节限制。
- 支持提取 `vmess`、`vless`、`trojan`、`ss`、`ssr`、`hysteria2`、`hy2`、`tuic` 节点链接。
- 节点内容使用 SHA-256 完全去重。
- 采集结果写入 `nodes`，默认状态为 `pending_test`。
- 来源写入 `node_sources`，记录成功、失败、冷却时间和内容哈希。
- 采集任务写入 `collection_runs`。
- 来源级采集结果写入 `collection_run_sources`。
- 后台新增触发采集、查看来源缓存和采集历史的基础页面。
- 后台 UI 保持中文，登录页密码默认隐藏并可切换显示。
- 配置 Git remote：`https://github.com/webhuage-debug/jiandiancaiji.git`。

### 修改文件

- 修改 `package.json`
- 修改 `.env.example`
- 修改 `apps/api/package.json`
- 修改 `apps/api/src/config.ts`
- 修改 `apps/api/src/db.ts`
- 修改 `apps/api/src/schema.ts`
- 修改 `apps/api/src/routes.ts`
- 修改 `apps/web/package.json`
- 修改 `apps/web/src/main.tsx`
- 修改 `apps/web/src/styles.css`
- 修改 `README.md`
- 修改 `docs/ARCHITECTURE.md`
- 修改 `docs/CHANGELOG.md`
- 修改 `docs/DEVELOPMENT_LOG.md`
- 修改 `docs/HANDOFF.md`
- 修改 `docs/SECURITY.md`
- 修改 `docs/TODO.md`
- 新增 `apps/api/src/collector/nodeParser.ts`
- 新增 `apps/api/src/collector/sourceDiscovery.ts`
- 新增 `apps/api/src/collector/http.ts`
- 新增 `apps/api/src/collector/collectionService.ts`

### 删除文件

- 无

### 运行测试

- 已执行：`node scripts/check-sensitive.mjs`，使用 Codex bundled Node 路径执行。
- 已执行：UTF-8 内容扫描，确认 `apps/web/src/main.tsx`、`apps/api/src/routes.ts` 无替换字符和明显乱码片段。
- 未执行：`npm install`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run typecheck`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run build`，当前环境没有可用 `npm` 命令。
- 未执行：Docker 构建，当前环境没有可用 `docker` 命令。

### 测试结果

- 敏感文件检查通过：`Sensitive file check passed for 32 tracked or pending files.`
- 未发现真实 `.env`、Token、数据库、日志、节点包或运行数据。
- 因本地环境缺少 `npm` 和 `docker`，依赖安装、类型检查、构建和真实采集需在 VPS 或 Docker 环境继续验证。

### 当前问题

- 当前环境无法执行 npm/Docker 构建验证。
- 真实采集依赖公网访问和 GitHub API，需在 VPS 或 Docker 环境验证。

### 下一步建议

- v0.3.0 实现基础连通性测试、失败剔除、候选节点池和延迟分布。
- 在 v0.2.0 部署后观察 GitHub API 限制和来源质量，再微调查询词。

### 敏感信息检查

- 本阶段不包含真实 `.env`、Token、数据库、节点包、运行日志。
- 节点数据只会在运行时写入 SQLite，不提交到 GitHub。

### Git commit 信息

- 已本地提交：`6263387 feat: add v0.2.0 public source collector`

### 是否已 push 到 GitHub

- 未 push 成功。已配置 `origin` 为 `https://github.com/webhuage-debug/jiandiancaiji.git`，但当前环境执行 `git push -u origin codex/v0.2.0-collector` 失败：`Could not resolve host: github.com`。
- 需要在网络/DNS 可访问 GitHub 的环境重试 push。

## 2026-05-23 v0.1.0

### 本次开发时间

- 2026-05-23 Asia/Shanghai

### 本次开发目标

- 从零创建 v0.1.0 项目基础版
- 完成基础目录结构、Docker Compose 部署、SQLite 初始化、管理后台基础页面、管理员登录、Session 管理、配置模板、Git 忽略规则和文档体系

### 已完成功能

- 创建 Node.js + TypeScript + Fastify 后端
- 创建 React + Vite 管理后台
- 后端可初始化 SQLite 数据库
- 首次部署时从 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 创建管理员
- 管理员密码使用 bcrypt 哈希存储
- 支持登录、退出登录、登录状态检查、修改密码接口
- 支持 Session Cookie 和 Session 过期
- 支持登录失败次数限制，失败过多临时锁定
- 创建 v0.1.0 仪表盘基础页面
- 创建 公开视频模式 前端开关雏形
- 预建后续节点来源、节点池、采集记录、测试记录、导出批次、领取统计、反馈、日志相关数据库表
- 创建 Dockerfile 与 docker-compose.yml
- 创建 `.env.example` 与 `.gitignore`
- 创建敏感文件检查脚本 `scripts/check-sensitive.mjs`

### 修改文件

- 新增 `package.json`
- 新增 `.gitignore`
- 新增 `.env.example`
- 新增 `Dockerfile`
- 新增 `docker-compose.yml`
- 新增 `apps/api/package.json`
- 新增 `apps/api/tsconfig.json`
- 新增 `apps/api/src/config.ts`
- 新增 `apps/api/src/db.ts`
- 新增 `apps/api/src/schema.ts`
- 新增 `apps/api/src/auth.ts`
- 新增 `apps/api/src/routes.ts`
- 新增 `apps/api/src/server.ts`
- 新增 `apps/web/package.json`
- 新增 `apps/web/tsconfig.json`
- 新增 `apps/web/index.html`
- 新增 `apps/web/vite.config.ts`
- 新增 `apps/web/src/main.tsx`
- 新增 `apps/web/src/styles.css`
- 新增 `scripts/check-sensitive.mjs`
- 新增 `README.md`
- 新增 `docs/HANDOFF.md`
- 新增 `docs/DEVELOPMENT_LOG.md`
- 新增 `docs/TODO.md`
- 新增 `docs/CHANGELOG.md`
- 新增 `docs/ARCHITECTURE.md`
- 新增 `docs/DEPLOY.md`
- 新增 `docs/SECURITY.md`

### 删除文件

- 无

### 运行测试

- 已执行：`node scripts/check-sensitive.mjs`，使用 Codex bundled Node 路径执行。
- 已执行：PowerShell 文件名扫描，确认没有 `.env`、数据库、日志、zip、运行数据目录文件进入待提交列表。
- 已执行：PowerShell Token 模式扫描，未发现真实 GitHub Token；命中项仅为敏感检查脚本自身的检测规则。
- 未执行：`npm install`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run typecheck`，当前环境没有可用 `npm` 命令。
- 未执行：`npm run build`，当前环境没有可用 `npm` 命令。
- 未执行：Docker 构建，当前环境没有可用 `docker` 命令。

### 测试结果

- 敏感文件检查通过：`Sensitive file check passed for 28 tracked or pending files.`
- 未发现真实 `.env`、数据库、日志、节点包、运行数据目录文件。
- 依赖安装、类型检查和构建验证受本地环境限制，需在具备 `npm` 或 Docker 的环境继续执行。

### 当前问题

- v0.1.0 尚未实现节点采集、测试、导出和公开领取页功能。
- 本地默认 `node.exe` 调用被系统拒绝，需要使用 Codex bundled Node 或 Docker 环境验证。
- 当前环境没有 `npm`、`docker`、`gh` 命令。
- 当前 Git 仓库没有 remote，无法直接创建 GitHub 私有仓库或 push。

### 下一步建议

- v0.2.0 实现公开来源发现、采集限速、节点协议提取和去重入库。
- 在 v0.2.0 前确认 GitHub 私有仓库远程地址和 push 权限。

### 敏感信息检查

- 已创建 `.gitignore`，禁止提交 `.env`、数据库、日志、节点包、节点数据和运行目录。
- 已创建 `scripts/check-sensitive.mjs` 用于提交前扫描。
- 本次不包含真实 Token、真实 `.env`、数据库、节点数据、运行日志或节点包。

### Git commit 信息

- 本阶段提交信息：`chore: initialize v0.1.0 foundation`
- 提交分支：`codex/v0.1.0-foundation`

### 是否已 push 到 GitHub

- 未 push。原因：当前环境没有 GitHub CLI，仓库也未配置 GitHub remote。需要提供私有仓库远程地址，或启用可创建私有仓库的 GitHub 工具后继续。
