import React from "react";
import ReactDOM from "react-dom/client";
import {
  Activity,
  BarChart3,
  Database,
  Download,
  Eye,
  EyeOff,
  FileArchive,
  Gauge,
  GitBranch,
  Home,
  Link2,
  ListFilter,
  LogOut,
  MessageSquare,
  Play,
  ScrollText,
  Settings,
  ShieldCheck,
  Trash2,
  Video
} from "lucide-react";
import "./styles.css";

type AuthStatus = {
  authenticated: boolean;
  user?: { id: number; username: string } | null;
};

type Summary = {
  version: string;
  systemStatus: string;
  candidateNodes: number;
  pendingNodes: number;
  failedNodes: number;
  collectedNodes: number;
  publishedBatches: number;
  latencyDistribution: Array<{ label: string; count: number }>;
};

type CollectionRun = {
  id: number;
  status: string;
  discovered_sources: number;
  fetched_sources: number;
  raw_nodes: number;
  inserted_nodes: number;
  error_count: number;
};

type TestRun = {
  id: number;
  status: string;
  tested_nodes: number;
  passed_nodes: number;
  failed_nodes: number;
  avg_latency_ms?: number;
};

type XrayQueueStats = {
  candidateTotal: number;
  xrayChecked: number;
  xrayUnchecked: number;
  realPassed: number;
  realFailed: number;
  skipped: number;
  avgRealLatencyMs?: number | null;
  tierHigh?: number;
  tierPremium?: number;
  tierCommunity?: number;
  tierBackup?: number;
  configured?: boolean;
  lastTestedAt?: string | null;
  runtime?: {
    status: string;
    currentBatch: number;
    currentBatchSize: number;
    processedThisRun: number;
    message: string;
    startedAt?: string | null;
    updatedAt?: string | null;
  };
};

type XrayOptions = {
  mode: string;
  limit: string;
  protocol: string;
  minLatencyMs: string;
  maxLatencyMs: string;
};

type NodeItem = {
  id: number;
  protocol: string;
  source_url?: string;
  source_type?: string;
  collected_at?: string;
  last_tested_at?: string;
  latency_ms?: number;
  real_latency_ms?: number;
  real_status?: string;
  real_tested_at?: string;
  test_method?: string;
  success_count?: number;
  failure_count?: number;
  quality_tier?: string;
  status: string;
  failure_reason?: string;
  exported_at?: string;
  export_batch_id?: number;
};

type ExportBatch = {
  id: number;
  batch_code: string;
  name: string;
  status: string;
  node_count: number;
  public_slug: string;
  quality_tier?: string | null;
  requires_passphrase?: number;
  allow_public_claim?: number;
  allow_automation?: number;
  allow_direct_download?: number;
  allow_hermes_file?: number;
  allow_hermes_link?: number;
  last_tested_at?: string | null;
  test_method?: string | null;
  pass_rate?: number | null;
  expires_at?: string | null;
  max_downloads?: number | null;
  ip_download_limit?: number | null;
  wrong_passphrase_limit?: number | null;
  created_at?: string;
};

type SourceItem = {
  id: number;
  url: string;
  source_type: string;
  status: string;
  success_count: number;
  failure_count: number;
  last_error?: string;
};

type BatchStat = {
  id: number;
  batch_code: string;
  name: string;
  status: string;
  node_count: number;
  public_slug: string;
  view_count?: number;
  passphrase_attempt_count?: number;
  passphrase_correct_count?: number;
  passphrase_wrong_count?: number;
  unlock_count?: number;
  download_count?: number;
  feedback_count?: number;
};

type ChannelStat = {
  source_platform: string;
  view_count?: number;
  passphrase_attempt_count?: number;
  passphrase_wrong_count?: number;
  passphrase_correct_count?: number;
  download_count?: number;
  feedback_count?: number;
  unusable_feedback_count?: number;
  last_seen_at?: string;
};

type FeedbackItem = {
  id: number;
  batch_code?: string;
  region?: string;
  carrier?: string;
  device?: string;
  client_app?: string;
  is_usable?: number | null;
  issue_type?: string;
  source_platform?: string;
  process_status?: string;
  process_note?: string;
  note?: string;
  created_at?: string;
};

type LogItem = {
  level: string;
  message: string;
  created_at: string;
};

type PublicBatch = {
  title: string;
  description: string;
  mode?: string;
  startsAt?: string | null;
  expiresAt?: string | null;
  remainingSeconds?: number;
  status?: string;
  riskStatus?: string;
  riskMessage?: string | null;
  outputCount?: number;
  rawUrl?: string | null;
  base64Url?: string | null;
};

type SubscriptionActivity = {
  id: number;
  name: string;
  video_note?: string;
  status: string;
  claim_slug: string;
  subscription_token: string;
  starts_at: string;
  expires_at: string;
  output_count: number;
  target_latency_ms: number;
  warning_latency_ms: number;
  remove_latency_ms: number;
  health_check_interval_minutes: number;
  last_health_check_at?: string | null;
  last_cache_generated_at?: string | null;
  last_replacement_count?: number;
  risk_status?: string | null;
  risk_message?: string | null;
  view_count?: number;
  raw_access_count?: number;
  base64_access_count?: number;
  feedback_count?: number;
  active_ip_count?: number;
  created_at?: string;
};

type SubscriptionFormState = {
  name: string;
  videoNote: string;
  passphrase: string;
  startsAt: string;
  expiresAt: string;
  outputCount: number;
  targetLatencyMs: number;
  warningLatencyMs: number;
  removeLatencyMs: number;
  healthCheckIntervalMinutes: number;
};

type ExportFormState = {
  name: string;
  count: number;
  maxLatencyMs: string;
  passphrase: string;
  minLatencyMs: string;
  protocol: string;
  qualityTier: string;
  realOnly: boolean;
  requiresPassphrase: boolean;
  allowPublicClaim: boolean;
  allowAutomation: boolean;
  allowDirectDownload: boolean;
  allowHermesFile: boolean;
  allowHermesLink: boolean;
  publish: boolean;
  expiresAt: string;
  maxDownloads: string;
  ipDownloadLimit: number;
  wrongPassphraseLimit: number;
};

type ViewKey =
  | "dashboard"
  | "nodes"
  | "collection"
  | "tests"
  | "failed"
  | "packages"
  | "subscriptions"
  | "claim"
  | "stats"
  | "feedback"
  | "automation"
  | "settings"
  | "logs";

const navItems: Array<{ key: ViewKey; label: string; icon: React.ReactNode }> = [
  { key: "dashboard", label: "首页仪表盘", icon: <Home size={17} /> },
  { key: "nodes", label: "节点池", icon: <Database size={17} /> },
  { key: "collection", label: "采集任务", icon: <GitBranch size={17} /> },
  { key: "tests", label: "测试记录", icon: <Activity size={17} /> },
  { key: "failed", label: "失效节点记录", icon: <ListFilter size={17} /> },
  { key: "packages", label: "节点包管理", icon: <FileArchive size={17} /> },
  { key: "subscriptions", label: "订阅管理", icon: <Link2 size={17} /> },
  { key: "claim", label: "领取页管理", icon: <Link2 size={17} /> },
  { key: "stats", label: "统计数据", icon: <BarChart3 size={17} /> },
  { key: "feedback", label: "反馈数据", icon: <MessageSquare size={17} /> },
  { key: "automation", label: "自动化接口", icon: <Link2 size={17} /> },
  { key: "settings", label: "系统设置", icon: <Settings size={17} /> },
  { key: "logs", label: "运行日志", icon: <ScrollText size={17} /> }
];

const statusText: Record<string, string> = {
  pending: "等待中",
  idle: "未开始",
  pending_test: "待测试",
  running: "进行中",
  paused: "已暂停",
  stopped: "已停止",
  completed: "已完成",
  failed: "失败",
  test_passed: "测试通过",
  test_failed: "测试不通过",
  exported: "已导出",
  removed: "已剔除",
  success: "成功",
  timeout: "连接超时",
  cancelled: "已取消",
  draft: "草稿",
  published: "已发布",
  closed: "已关闭",
  expired: "已过期",
  replaced: "已替换",
  available: "可用",
  unavailable: "不可用",
  real_passed: "真实可用",
  real_failed: "真实检测失败",
  xray_not_configured: "Xray 未配置",
  xray_unsupported_protocol: "协议暂不支持",
  xray_converter_pending: "转换器待完善",
  xray_start_failed: "Xray 启动失败",
  proxy_timeout: "代理访问超时",
  invalid_test_url: "测试地址无效"
};

const qualityText: Record<string, string> = {
  high: "高质量节点包",
  premium: "普通优质节点包",
  community: "社群福利节点包",
  backup: "备用节点包"
};

const failureText: Record<string, string> = {
  timeout: "连接超时",
  connection_failed: "连接失败",
  tcp_failed: "TCP 连接失败",
  test_failed: "测试不通过",
  invalid_config: "配置无效",
  protocol_error: "协议错误",
  dns_failed: "DNS 解析失败",
  proxy_failed: "代理访问失败",
  parse_failed: "解析失败",
  unsupported_protocol: "协议暂不支持",
  xray_not_configured: "Xray 未配置",
  xray_probe_failed: "Xray 启动检查失败",
  xray_converter_pending: "Xray 转换器待完善",
  xray_start_failed: "Xray 启动失败",
  proxy_timeout: "代理访问超时",
  invalid_test_url: "测试地址无效",
  unknown: "未知原因"
};

const issueText: Record<string, string> = {
  connection_failed: "无法连接",
  high_latency: "延迟太高",
  youtube_stuck: "YouTube 卡顿",
  chatgpt_failed: "ChatGPT 打不开",
  tiktok_failed: "TikTok 不通",
  partial_available: "部分节点可用",
  all_failed: "全部不可用",
  import_help: "不会导入",
  download_failed: "下载失败",
  other: "其他问题"
};

const processText: Record<string, string> = {
  pending: "未处理",
  viewed: "已查看",
  resolved: "已解决",
  invalid: "无效反馈",
  regenerate: "需要重新生成节点包"
};

function zhStatus(value?: string | null) {
  if (!value) return "-";
  return statusText[value] ?? value;
}

function zhFailure(value?: string | null) {
  if (!value) return "-";
  return failureText[value] ?? value;
}

function zhIssue(value?: string | null) {
  if (!value) return "-";
  return issueText[value] ?? value;
}

function zhProcess(value?: string | null) {
  if (!value) return "未处理";
  return processText[value] ?? value;
}

function zhQuality(value?: string | null) {
  if (!value) return "未分档";
  return qualityText[value] ?? value;
}

function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  return fetch(input, {
    credentials: "same-origin",
    ...init
  });
}

function App() {
  const publicMatch = window.location.pathname.match(/^\/(?:p|r)\/([^/]+)/);
  if (publicMatch) return <PublicSubscriptionClaimPage slug={publicMatch[1]} />;
  return <AdminApp />;
}

function AdminApp() {
  const [auth, setAuth] = React.useState<AuthStatus | null>(null);

  React.useEffect(() => {
    apiFetch("/api/auth/status")
      .then((res) => res.json())
      .then(setAuth)
      .catch(() => setAuth({ authenticated: false }));
  }, []);

  if (!auth) return <div className="boot">正在检查登录状态...</div>;
  if (!auth.authenticated) return <Login onLogin={setAuth} />;
  return <Dashboard user={auth.user!} onLogout={() => setAuth({ authenticated: false })} />;
}

function Login({ onLogin }: { onLogin: (auth: AuthStatus) => void }) {
  const [username, setUsername] = React.useState("admin");
  const [password, setPassword] = React.useState("");
  const [visible, setVisible] = React.useState(false);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    const res = await apiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    setLoading(false);
    if (!res.ok) {
      setError(data.message ?? "登录失败");
      return;
    }
    onLogin({ authenticated: true, user: data.user });
  }

  return (
    <main className="login-shell">
      <section className="login-panel">
        <div className="brand-row">
          <ShieldCheck size={30} />
          <div>
            <h1>Public Node Admin</h1>
            <p>个人 VPS 公开节点采集后台</p>
          </div>
        </div>
        <form onSubmit={submit} className="login-form">
          <label>
            管理员账号
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label>
            登录密码
            <div className="password-box">
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type={visible ? "text" : "password"}
                autoComplete="current-password"
              />
              <button type="button" aria-label={visible ? "隐藏密码" : "显示密码"} onClick={() => setVisible((value) => !value)}>
                {visible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </label>
          {error && <div className="error">{error}</div>}
          <button className="primary" disabled={loading}>{loading ? "登录中..." : "登录后台"}</button>
        </form>
      </section>
    </main>
  );
}

function Dashboard({ user, onLogout }: { user: { username: string }; onLogout: () => void }) {
  const [activeView, setActiveView] = React.useState<ViewKey>("dashboard");
  const [summary, setSummary] = React.useState<Summary | null>(null);
  const [sources, setSources] = React.useState<SourceItem[]>([]);
  const [runs, setRuns] = React.useState<CollectionRun[]>([]);
  const [testRuns, setTestRuns] = React.useState<TestRun[]>([]);
  const [nodes, setNodes] = React.useState<NodeItem[]>([]);
  const [failedNodes, setFailedNodes] = React.useState<NodeItem[]>([]);
  const [batches, setBatches] = React.useState<ExportBatch[]>([]);
  const [subscriptions, setSubscriptions] = React.useState<SubscriptionActivity[]>([]);
  const [stats, setStats] = React.useState<BatchStat[]>([]);
  const [channelStats, setChannelStats] = React.useState<ChannelStat[]>([]);
  const [feedback, setFeedback] = React.useState<FeedbackItem[]>([]);
  const [logs, setLogs] = React.useState<LogItem[]>([]);
  const [videoMode, setVideoMode] = React.useState(false);
  const [collecting, setCollecting] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [xrayStats, setXrayStats] = React.useState<XrayQueueStats | null>(null);
  const [xrayOptions, setXrayOptions] = React.useState<XrayOptions>({
    mode: "untested",
    limit: "50",
    protocol: "",
    minLatencyMs: "",
    maxLatencyMs: ""
  });
  const [exporting, setExporting] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const [nodeFilters, setNodeFilters] = React.useState({
    protocol: "",
    status: "test_passed",
    maxLatency: "",
    exported: ""
  });
  const [exportForm, setExportForm] = React.useState({
    name: "本期候选节点",
    count: 10,
    minLatencyMs: "",
    maxLatencyMs: "",
    protocol: "",
    qualityTier: "",
    realOnly: false,
    passphrase: "",
    requiresPassphrase: true,
    allowPublicClaim: true,
    allowAutomation: false,
    allowDirectDownload: false,
    allowHermesFile: false,
    allowHermesLink: false,
    publish: false,
    expiresAt: "",
    maxDownloads: "",
    ipDownloadLimit: 3,
    wrongPassphraseLimit: 8
  });
  const [subscriptionForm, setSubscriptionForm] = React.useState<SubscriptionFormState>({
    name: "本期 YouTube 免费节点订阅",
    videoNote: "",
    passphrase: "",
    startsAt: "",
    expiresAt: "",
    outputCount: 10,
    targetLatencyMs: 200,
    warningLatencyMs: 300,
    removeLatencyMs: 500,
    healthCheckIntervalMinutes: 5
  });

  const refresh = React.useCallback(async () => {
    const nodeQuery = new URLSearchParams({ limit: "50" });
    if (nodeFilters.protocol) nodeQuery.set("protocol", nodeFilters.protocol);
    if (nodeFilters.status) nodeQuery.set("status", nodeFilters.status);
    if (nodeFilters.maxLatency) nodeQuery.set("maxLatency", nodeFilters.maxLatency);
    if (nodeFilters.exported) nodeQuery.set("exported", nodeFilters.exported);

    const [
      summaryRes,
      sourcesRes,
      runsRes,
      testRunsRes,
      nodesRes,
      failedNodesRes,
      batchesRes,
      subscriptionsRes,
      videoModeRes,
      statsRes,
      channelStatsRes,
      feedbackRes,
      xrayStatsRes,
      logsRes
    ] = await Promise.all([
      apiFetch("/api/dashboard/summary"),
      apiFetch("/api/sources"),
      apiFetch("/api/collection-runs"),
      apiFetch("/api/test-runs"),
      apiFetch(`/api/nodes?${nodeQuery.toString()}`),
      apiFetch("/api/nodes?status=test_failed&limit=50"),
      apiFetch("/api/export-batches"),
      apiFetch("/api/subscriptions"),
      apiFetch("/api/settings/video-mode"),
      apiFetch("/api/stats/batches"),
      apiFetch("/api/stats/channels"),
      apiFetch("/api/feedback"),
      apiFetch("/api/xray-test-runs/stats"),
      apiFetch("/api/logs")
    ]);
    setSummary(await summaryRes.json());
    setSources((await sourcesRes.json()).items ?? []);
    setRuns((await runsRes.json()).items ?? []);
    setTestRuns((await testRunsRes.json()).items ?? []);
    setNodes((await nodesRes.json()).items ?? []);
    setFailedNodes((await failedNodesRes.json()).items ?? []);
    setBatches((await batchesRes.json()).items ?? []);
    setSubscriptions((await subscriptionsRes.json()).items ?? []);
    setVideoMode(Boolean((await videoModeRes.json()).enabled));
    setStats((await statsRes.json()).items ?? []);
    setChannelStats((await channelStatsRes.json()).items ?? []);
    setFeedback((await feedbackRes.json()).items ?? []);
    setXrayStats(await xrayStatsRes.json());
    setLogs((await logsRes.json()).items ?? []);
  }, [nodeFilters]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  React.useEffect(() => {
    if (!testing) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const res = await apiFetch("/api/xray-test-runs/stats");
        setXrayStats(await res.json());
      } catch {
        // keep the running test quiet; the main request will surface errors
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [testing]);

  async function logout() {
    await apiFetch("/api/auth/logout", { method: "POST" });
    onLogout();
  }

  async function runCollector() {
    setCollecting(true);
    setNotice("采集任务已开始，系统会限速抓取公开 URL...");
    const res = await apiFetch("/api/collection-runs", { method: "POST" });
    const data = await res.json();
    setCollecting(false);
    if (!res.ok) {
      setNotice(data.message ?? "采集失败");
      return;
    }
    setNotice(`本次采集原始节点 ${data.summary.rawNodes} 条，新增入库 ${data.summary.insertedNodes} 条。`);
    await refresh();
  }

  async function runTester() {
    setTesting(true);
    setNotice("基础测试已开始，正在并发测试前 100 条待测试节点，请稍候...");
    const res = await apiFetch("/api/test-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 100 })
    });
    const data = await res.json();
    setTesting(false);
    if (!res.ok) {
      setNotice(data.message ?? "测试失败");
      return;
    }
    setNotice(`本次测试 ${data.summary.testedNodes} 条，通过 ${data.summary.passedNodes} 条，失败剔除 ${data.summary.failedNodes} 条。`);
    await refresh();
  }

  async function runXrayTester(overrides: Partial<XrayOptions> = {}) {
    const options = { ...xrayOptions, ...overrides };
    setTesting(true);
    setNotice("Xray-core 正在进行全量真实检测。系统会每批检测 50 条，并以低并发持续运行，直到所有候选节点检测完成。");
    const res = await apiFetch("/api/xray-test-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: options.mode,
        limit: Number(options.limit || 50),
        protocol: options.protocol || undefined,
        minLatencyMs: options.minLatencyMs ? Number(options.minLatencyMs) : undefined,
        maxLatencyMs: options.maxLatencyMs ? Number(options.maxLatencyMs) : undefined,
        includeRecentFailures: options.mode === "failed"
      })
    });
    const data = await res.json();
    setTesting(false);
    if (!res.ok) {
      setNotice(data.message ?? "Xray-core 真实检测失败");
      return;
    }
    if (!data.summary.configured) {
      setNotice("Xray-core 未启用或未配置路径，本次只记录跳过状态，没有启动临时代理。");
    } else {
      setNotice(`Xray-core 全量真实检测完成：候选 ${data.summary.queueAfter.candidateTotal} 条，已检测 ${data.summary.queueAfter.xrayChecked} 条，真实可用 ${data.summary.queueAfter.realPassed} 条，真实失败 ${data.summary.queueAfter.realFailed} 条。`);
    }
    await refresh();
  }

  async function pauseXrayTester() {
    await apiFetch("/api/xray-test-runs/pause", { method: "POST" });
    setNotice("Xray-core 检测已请求暂停。当前批次完成后暂停，已完成结果已保存。");
    await refresh();
  }

  async function stopXrayTester() {
    await apiFetch("/api/xray-test-runs/stop", { method: "POST" });
    setNotice("Xray-core 检测已请求停止。当前批次完成后停止，并清理临时进程。");
    await refresh();
  }

  async function createExport(event: React.FormEvent) {
    event.preventDefault();
    if (exportForm.requiresPassphrase && !exportForm.passphrase.trim()) {
      setNotice("请先填写本期口令，口令会同时用于领取页验证和 zip 解压。");
      return;
    }
    setExporting(true);
    setNotice("正在生成节点包...");
    const res = await apiFetch("/api/export-batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: exportForm.name,
        count: Number(exportForm.count),
        minLatencyMs: exportForm.minLatencyMs ? Number(exportForm.minLatencyMs) : undefined,
        maxLatencyMs: exportForm.maxLatencyMs ? Number(exportForm.maxLatencyMs) : undefined,
        protocol: exportForm.protocol || undefined,
        qualityTier: exportForm.qualityTier || undefined,
        realOnly: exportForm.realOnly,
        passphrase: exportForm.passphrase,
        requiresPassphrase: exportForm.requiresPassphrase,
        allowPublicClaim: exportForm.allowPublicClaim,
        allowAutomation: exportForm.allowAutomation,
        allowDirectDownload: exportForm.allowDirectDownload,
        allowHermesFile: exportForm.allowHermesFile,
        allowHermesLink: exportForm.allowHermesLink,
        publish: false,
        expiresAt: exportForm.expiresAt ? new Date(exportForm.expiresAt).toISOString() : undefined,
        maxDownloads: exportForm.maxDownloads ? Number(exportForm.maxDownloads) : undefined,
        ipDownloadLimit: Number(exportForm.ipDownloadLimit),
        wrongPassphraseLimit: Number(exportForm.wrongPassphraseLimit),
        sort: "latency_asc",
        includeExported: false
      })
    });
    const data = await res.json();
    setExporting(false);
    if (!res.ok) {
      setNotice(data.message === "no eligible nodes for export" ? "没有符合条件的已通过节点，请先运行基础测试或放宽最大延迟。" : data.message ?? "导出失败");
      return;
    }
    setNotice(`节点包已生成草稿：${data.batch.batchCode}，数量 ${data.batch.nodeCount} 条。点击“发布此批次”后粉丝才能领取。`);
    setActiveView("packages");
    setExportForm((value) => ({ ...value, passphrase: "" }));
    await refresh();
  }

  async function toggleVideoMode() {
    const next = !videoMode;
    await apiFetch("/api/settings/video-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: next })
    });
    await refresh();
  }

  async function publishBatch(batch: ExportBatch) {
    setNotice(`正在发布批次 ${batch.batch_code}，旧的公开批次会自动标记为已替换。`);
    const res = await apiFetch(`/api/export-batches/${batch.id}/publish`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "发布失败");
      return;
    }
    setNotice(`批次 ${batch.batch_code} 已发布，公开领取页现在可用。`);
    await refresh();
  }

  async function closeBatch(batch: ExportBatch) {
    setNotice(`正在关闭批次 ${batch.batch_code}...`);
    const res = await apiFetch(`/api/export-batches/${batch.id}/close`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "关闭失败");
      return;
    }
    setNotice(`批次 ${batch.batch_code} 已关闭。`);
    await refresh();
  }

  async function deleteDraft(batch: ExportBatch) {
    setNotice(`正在删除草稿 ${batch.batch_code}...`);
    const res = await apiFetch(`/api/export-batches/${batch.id}`, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "删除失败");
      return;
    }
    setNotice(`草稿 ${batch.batch_code} 已删除。`);
    await refresh();
  }

  async function preflightBatch(batch: ExportBatch) {
    setNotice(`正在检查批次 ${batch.batch_code}，这是发布前可选检查，不会强制阻止发布...`);
    const res = await apiFetch(`/api/export-batches/${batch.id}/preflight`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "发布前检查失败");
      return;
    }
    const summary = data.summary;
    setNotice(`发布前检查完成：通过率 ${summary.passRate}% ，平均延迟 ${summary.avgLatency ?? "-"}ms，风险 ${riskText(summary.riskLevel)}。${summary.message ?? ""}`);
    await refresh();
  }

  async function createSubscription(event: React.FormEvent) {
    event.preventDefault();
    if (!subscriptionForm.passphrase.trim()) {
      setNotice("请先填写本期视频口令，粉丝输入正确口令后才能看到订阅链接。");
      return;
    }
    setNotice("正在创建本期订阅活动，并从 Xray 真实可用池生成订阅缓存...");
    const res = await apiFetch("/api/subscriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: subscriptionForm.name,
        videoNote: subscriptionForm.videoNote,
        passphrase: subscriptionForm.passphrase,
        startsAt: subscriptionForm.startsAt ? new Date(subscriptionForm.startsAt).toISOString() : undefined,
        expiresAt: subscriptionForm.expiresAt ? new Date(subscriptionForm.expiresAt).toISOString() : undefined,
        outputCount: Number(subscriptionForm.outputCount),
        targetLatencyMs: Number(subscriptionForm.targetLatencyMs),
        warningLatencyMs: Number(subscriptionForm.warningLatencyMs),
        removeLatencyMs: Number(subscriptionForm.removeLatencyMs),
        healthCheckIntervalMinutes: Number(subscriptionForm.healthCheckIntervalMinutes)
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "订阅活动创建失败");
      return;
    }
    setNotice("订阅活动已创建：粉丝通过领取页输入视频口令后，可以复制 raw / base64 订阅链接。");
    setSubscriptionForm((value) => ({ ...value, passphrase: "" }));
    setActiveView("subscriptions");
    await refresh();
  }

  async function rebuildSubscription(activity: SubscriptionActivity) {
    setNotice(`正在重建订阅输出池：${activity.name}`);
    const res = await apiFetch(`/api/subscriptions/${activity.id}/rebuild`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "订阅输出池重建失败");
      return;
    }
    setNotice(`订阅输出池已重建：目标 ${data.summary?.target ?? activity.output_count} 条，当前选中 ${data.summary?.selected ?? 0} 条。`);
    await refresh();
  }

  async function healthCheckSubscription(activity: SubscriptionActivity) {
    setNotice(`正在执行订阅健康检查：${activity.name}`);
    const res = await apiFetch(`/api/subscriptions/${activity.id}/health-check`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "订阅健康检查失败");
      return;
    }
    setNotice(`订阅健康检查完成：替换/移除 ${data.summary?.removed ?? 0} 条，当前输出 ${data.summary?.currentCount ?? 0} 条。${data.summary?.riskMessage ?? ""}`);
    await refresh();
  }

  async function refreshSubscriptionCache(activity: SubscriptionActivity) {
    setNotice(`正在刷新订阅缓存：${activity.name}`);
    const res = await apiFetch(`/api/subscriptions/${activity.id}/cache`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "订阅缓存刷新失败");
      return;
    }
    setNotice(`订阅缓存已刷新：当前输出 ${data.summary?.nodeCount ?? 0} 条。${data.summary?.riskMessage ?? ""}`);
    await refresh();
  }

  async function updateFeedbackStatus(item: FeedbackItem, processStatus: string) {
    setNotice("正在更新反馈处理状态...");
    const res = await apiFetch(`/api/feedback/${item.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ processStatus })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setNotice(data.message ?? "反馈状态更新失败");
      return;
    }
    setNotice("反馈处理状态已更新。");
    await refresh();
  }

  const currentNav = navItems.find((item) => item.key === activeView) ?? navItems[0];
  const displayUser = videoMode ? "已隐藏" : user.username;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-title"><Gauge size={24} /> 管理后台</div>
        <nav aria-label="后台菜单">
          {navItems.map((item) => (
            <button
              key={item.key}
              className={item.key === activeView ? "nav active" : "nav"}
              onClick={() => setActiveView(item.key)}
              type="button"
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>
      </aside>
      <section className="content">
        <header className="topbar">
          <div>
            <h1>{currentNav.label}</h1>
            <p>v1.1.0：升级为自动节点订阅池，粉丝端以 raw / base64 订阅链接为主。</p>
          </div>
          <div className="top-actions">
            <button className={videoMode ? "icon active" : "icon"} onClick={toggleVideoMode} title="公开视频模式">
              <Video size={18} />
              公开视频模式
            </button>
            <span className="user">管理员：{displayUser}</span>
            <button className="icon" onClick={logout}><LogOut size={18} /> 退出</button>
          </div>
        </header>

        {notice && <div className="notice">{notice}</div>}

        {activeView === "dashboard" && (
          <>
            <Metrics summary={summary} />
            <LatencyDistribution summary={summary} />
            <NodePreview title="低延迟候选节点预览" nodes={nodes.slice(0, 8)} />
            <BatchTable batches={batches} compact videoMode={videoMode} onPublish={publishBatch} onClose={closeBatch} onDeleteDraft={deleteDraft} onPreflight={preflightBatch} />
          </>
        )}

        {activeView === "nodes" && (
          <NodesPanel
            nodes={nodes}
            filters={nodeFilters}
            onFiltersChange={setNodeFilters}
            onRefresh={refresh}
          />
        )}

        {activeView === "collection" && (
          <CollectionPanel runs={runs} sources={sources} videoMode={videoMode} collecting={collecting} onRun={runCollector} />
        )}

        {activeView === "tests" && (
          <TestPanel
            runs={testRuns}
            testing={testing}
            xrayStats={xrayStats}
            xrayOptions={xrayOptions}
            setXrayOptions={setXrayOptions}
            onRun={runTester}
            onRunXray={runXrayTester}
            onPauseXray={pauseXrayTester}
            onStopXray={stopXrayTester}
          />
        )}

        {activeView === "failed" && (
          <NodePreview title="失效节点记录" nodes={failedNodes} />
        )}

        {activeView === "packages" && (
          <ExportPanel form={exportForm} setForm={setExportForm} exporting={exporting} onSubmit={createExport} batches={batches} videoMode={videoMode} onPublish={publishBatch} onClose={closeBatch} onDeleteDraft={deleteDraft} onPreflight={preflightBatch} />
        )}

        {activeView === "subscriptions" && (
          <SubscriptionPanel
            form={subscriptionForm}
            setForm={setSubscriptionForm}
            activities={subscriptions}
            videoMode={videoMode}
            onSubmit={createSubscription}
            onRebuild={rebuildSubscription}
            onHealthCheck={healthCheckSubscription}
            onRefreshCache={refreshSubscriptionCache}
          />
        )}

        {activeView === "claim" && (
          <ClaimPanel batches={batches} videoMode={videoMode} onPublish={publishBatch} onClose={closeBatch} onDeleteDraft={deleteDraft} onPreflight={preflightBatch} />
        )}

        {activeView === "stats" && (
          <StatsPanel stats={stats} channelStats={channelStats} />
        )}

        {activeView === "feedback" && (
          <FeedbackPanel feedback={feedback} onStatusChange={updateFeedbackStatus} />
        )}

        {activeView === "automation" && (
          <AutomationPanel batches={batches} videoMode={videoMode} />
        )}

        {activeView === "settings" && (
          <SettingsPanel videoMode={videoMode} onToggleVideoMode={toggleVideoMode} summary={summary} />
        )}

        {activeView === "logs" && (
          <LogsPanel logs={logs} />
        )}
      </section>
    </main>
  );
}

function Metrics({ summary }: { summary: Summary | null }) {
  return (
    <section className="metrics">
      <Metric label="已采集节点" value={summary?.collectedNodes ?? 0} />
      <Metric label="待测试节点" value={summary?.pendingNodes ?? 0} />
      <Metric label="候选节点" value={summary?.candidateNodes ?? 0} />
      <Metric label="失败/剔除" value={summary?.failedNodes ?? 0} />
    </section>
  );
}

function NodesPanel({
  nodes,
  filters,
  onFiltersChange,
  onRefresh
}: {
  nodes: NodeItem[];
  filters: { protocol: string; status: string; maxLatency: string; exported: string };
  onFiltersChange: React.Dispatch<React.SetStateAction<{ protocol: string; status: string; maxLatency: string; exported: string }>>;
  onRefresh: () => void;
}) {
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>候选节点池</h2>
          <p className="muted compact">默认只显示基础测试通过的节点，可以按协议、状态、延迟和导出状态筛选。</p>
        </div>
        <button className="primary small" onClick={onRefresh} type="button">刷新</button>
      </div>
      <div className="filter-form">
        <label>
          协议
          <select value={filters.protocol} onChange={(event) => onFiltersChange((value) => ({ ...value, protocol: event.target.value }))}>
            <option value="">全部</option>
            <option value="vmess">vmess</option>
            <option value="vless">vless</option>
            <option value="trojan">trojan</option>
            <option value="ss">ss</option>
            <option value="ssr">ssr</option>
            <option value="hysteria2">hysteria2</option>
            <option value="hy2">hy2</option>
            <option value="tuic">tuic</option>
          </select>
        </label>
        <label>
          状态
          <select value={filters.status} onChange={(event) => onFiltersChange((value) => ({ ...value, status: event.target.value }))}>
            <option value="test_passed">测试通过</option>
            <option value="pending_test">待测试</option>
            <option value="test_failed">测试失败</option>
            <option value="exported">已导出</option>
            <option value="">全部</option>
          </select>
        </label>
        <label>
          最大延迟 ms
          <input value={filters.maxLatency} placeholder="例如 300" onChange={(event) => onFiltersChange((value) => ({ ...value, maxLatency: event.target.value }))} />
        </label>
        <label>
          导出状态
          <select value={filters.exported} onChange={(event) => onFiltersChange((value) => ({ ...value, exported: event.target.value }))}>
            <option value="">全部</option>
            <option value="false">未导出</option>
            <option value="true">已导出</option>
          </select>
        </label>
      </div>
      <NodeTable nodes={nodes} />
    </section>
  );
}

function CollectionPanel({
  runs,
  sources,
  videoMode,
  collecting,
  onRun
}: {
  runs: CollectionRun[];
  sources: SourceItem[];
  videoMode: boolean;
  collecting: boolean;
  onRun: () => void;
}) {
  return (
    <>
      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>采集任务</h2>
            <p className="muted compact">采集任务已限制频率和并发，只抓取公开 URL。</p>
          </div>
          <button className="primary small" onClick={onRun} disabled={collecting}>
            <Play size={16} />
            {collecting ? "采集中..." : "开始采集"}
          </button>
        </div>
        <RunTable runs={runs} />
      </section>
      <SourceCache sources={sources} videoMode={videoMode} />
    </>
  );
}

function TestPanel({
  runs,
  testing,
  xrayStats,
  xrayOptions,
  setXrayOptions,
  onRun,
  onRunXray,
  onPauseXray,
  onStopXray
}: {
  runs: TestRun[];
  testing: boolean;
  xrayStats: XrayQueueStats | null;
  xrayOptions: XrayOptions;
  setXrayOptions: React.Dispatch<React.SetStateAction<XrayOptions>>;
  onRun: () => void;
  onRunXray: (overrides?: Partial<XrayOptions>) => void;
  onPauseXray: () => void;
  onStopXray: () => void;
}) {
  const usableRate = xrayStats?.xrayChecked ? Math.round((xrayStats.realPassed / xrayStats.xrayChecked) * 1000) / 10 : 0;
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>基础测试</h2>
          <p className="muted compact">只做后台初筛 TCP 连通性测试，失败节点不进入候选池。</p>
        </div>
        <div className="row-actions">
          <button className="primary small" onClick={onRun} disabled={testing}>
            <Activity size={16} />
            {testing ? "测试中..." : "开始基础测试"}
          </button>
          <button className="icon" onClick={() => onRunXray()} disabled={testing}>
            <Activity size={16} />
            Xray 真实检测
          </button>
        </div>
      </div>
      <div className="notice">
        {xrayStats?.configured
          ? "Xray-core 已启用：当前使用真实代理检测，临时代理仅监听 127.0.0.1，低并发队列运行。"
          : "Xray-core 未启用，请配置内核路径。配置完成后，系统会每批检测 50 条并自动持续检测全部未检测候选节点。"}
      </div>
      <div className="metric-grid compact">
        <article><span>候选节点总数</span><strong>{xrayStats?.candidateTotal ?? 0}</strong></article>
        <article><span>已真实检测</span><strong>{xrayStats?.xrayChecked ?? 0}</strong></article>
        <article><span>未真实检测</span><strong>{xrayStats?.xrayUnchecked ?? 0}</strong></article>
        <article><span>真实可用</span><strong>{xrayStats?.realPassed ?? 0}</strong></article>
        <article><span>真实失败</span><strong>{xrayStats?.realFailed ?? 0}</strong></article>
        <article><span>真实可用率</span><strong>{usableRate}%</strong></article>
        <article><span>平均真实延迟</span><strong>{xrayStats?.avgRealLatencyMs ? `${xrayStats.avgRealLatencyMs}ms` : "-"}</strong></article>
        <article><span>队列状态</span><strong>{zhStatus(xrayStats?.runtime?.status)}</strong></article>
      </div>
      <div className="metric-grid compact">
        <article><span>0-100ms</span><strong>{xrayStats?.tierHigh ?? 0}</strong></article>
        <article><span>100-200ms</span><strong>{xrayStats?.tierPremium ?? 0}</strong></article>
        <article><span>200-300ms</span><strong>{xrayStats?.tierCommunity ?? 0}</strong></article>
        <article><span>300ms 以上</span><strong>{xrayStats?.tierBackup ?? 0}</strong></article>
        <article><span>当前批次</span><strong>第 {xrayStats?.runtime?.currentBatch ?? 0} 批</strong></article>
        <article><span>当前批次数量</span><strong>{xrayStats?.runtime?.currentBatchSize ?? 0}</strong></article>
        <article><span>本轮已处理</span><strong>{xrayStats?.runtime?.processedThisRun ?? 0}</strong></article>
        <article><span>最后检测时间</span><strong>{xrayStats?.lastTestedAt ? formatTime(xrayStats.lastTestedAt) : "-"}</strong></article>
      </div>
      <div className="filter-form">
        <label>
          检测范围
          <select value={xrayOptions.mode} onChange={(event) => setXrayOptions((value) => ({ ...value, mode: event.target.value }))}>
            <option value="untested">只检测未做过 Xray 的节点</option>
            <option value="all">检测全部未检测候选节点</option>
            <option value="failed">重新检测失败节点</option>
            <option value="range">按延迟区间检测</option>
            <option value="current">检测当前候选批次</option>
          </select>
        </label>
        <label>
          每批检测数量
          <select value={xrayOptions.limit} onChange={(event) => setXrayOptions((value) => ({ ...value, limit: event.target.value }))}>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="200">200</option>
          </select>
        </label>
        <label>
          协议
          <select value={xrayOptions.protocol} onChange={(event) => setXrayOptions((value) => ({ ...value, protocol: event.target.value }))}>
            <option value="">全部</option>
            <option value="vless">VLESS</option>
            <option value="vmess">VMess</option>
            <option value="trojan">Trojan</option>
            <option value="ss">Shadowsocks</option>
          </select>
        </label>
        <label>
          最小延迟
          <input value={xrayOptions.minLatencyMs} onChange={(event) => setXrayOptions((value) => ({ ...value, minLatencyMs: event.target.value }))} placeholder="例如 0" />
        </label>
        <label>
          最大延迟
          <input value={xrayOptions.maxLatencyMs} onChange={(event) => setXrayOptions((value) => ({ ...value, maxLatencyMs: event.target.value }))} placeholder="例如 300" />
        </label>
      </div>
      <div className="row-actions">
        <button className="primary small" onClick={() => onRunXray({ mode: "untested", limit: "50" })} disabled={testing}>
          <Activity size={16} />
          {testing ? "检测中..." : "开始全量真实检测"}
        </button>
        <button className="icon" onClick={onPauseXray}>暂停检测</button>
        <button className="icon" onClick={() => onRunXray({ mode: "untested", limit: "50" })} disabled={testing}>继续检测</button>
        <button className="icon" onClick={onStopXray}>停止检测</button>
      </div>
      <TestRunTable runs={runs} />
    </section>
  );
}

function ExportPanel({
  form,
  setForm,
  exporting,
  onSubmit,
  batches,
  videoMode,
  onPublish,
  onClose,
  onDeleteDraft,
  onPreflight
}: {
  form: ExportFormState;
  setForm: React.Dispatch<React.SetStateAction<ExportFormState>>;
  exporting: boolean;
  onSubmit: (event: React.FormEvent) => void;
  batches: ExportBatch[];
  videoMode: boolean;
  onPublish: (batch: ExportBatch) => void;
  onClose: (batch: ExportBatch) => void;
  onDeleteDraft: (batch: ExportBatch) => void;
  onPreflight: (batch: ExportBatch) => void;
}) {
  const currentBatch = batches.find((batch) => batch.status === "published");
  const drafts = batches.filter((batch) => batch.status === "draft");
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>节点包导出</h2>
          <p className="muted compact">生成节点包后默认是草稿，不会公开。只有手动发布后，粉丝才能通过公开领取页下载。</p>
        </div>
      </div>
      <div className="notice">安全提示：生成节点包 ≠ 公开发布。误触生成的包只会留在草稿，不会影响当前粉丝领取页。</div>
      <form className="export-form" onSubmit={onSubmit}>
        <label>
          批次名称
          <input value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} />
        </label>
        <label>
          导出数量
          <input type="number" min="1" max="1000" value={form.count} onChange={(event) => setForm((value) => ({ ...value, count: Number(event.target.value) }))} />
        </label>
        <label>
          最小延迟 ms
          <input placeholder="例如 100" value={form.minLatencyMs} onChange={(event) => setForm((value) => ({ ...value, minLatencyMs: event.target.value }))} />
        </label>
        <label>
          最大延迟 ms
          <input placeholder="例如 300" value={form.maxLatencyMs} onChange={(event) => setForm((value) => ({ ...value, maxLatencyMs: event.target.value }))} />
        </label>
        <label>
          协议筛选
          <select value={form.protocol} onChange={(event) => setForm((value) => ({ ...value, protocol: event.target.value }))}>
            <option value="">全部协议</option>
            <option value="vless">VLESS</option>
            <option value="vmess">VMess</option>
            <option value="trojan">Trojan</option>
            <option value="ss">Shadowsocks</option>
          </select>
        </label>
        <label>
          节点包档位
          <select value={form.qualityTier} onChange={(event) => setForm((value) => ({ ...value, qualityTier: event.target.value }))}>
            <option value="">自动判断</option>
            <option value="high">0-100ms 高质量包</option>
            <option value="premium">100-200ms 普通优质包</option>
            <option value="community">200-300ms 社群福利包</option>
            <option value="backup">300ms 以上备用包</option>
          </select>
        </label>
        <label>
          本期口令
          <input type="password" value={form.passphrase} onChange={(event) => setForm((value) => ({ ...value, passphrase: event.target.value }))} required={form.requiresPassphrase} />
        </label>
        <label>
          有效期
          <input type="datetime-local" value={form.expiresAt} onChange={(event) => setForm((value) => ({ ...value, expiresAt: event.target.value }))} />
        </label>
        <label>
          总下载上限
          <input placeholder="长期可留空" value={form.maxDownloads} onChange={(event) => setForm((value) => ({ ...value, maxDownloads: event.target.value }))} />
        </label>
        <label>
          单 IP 下载
          <input type="number" min="1" max="100" value={form.ipDownloadLimit} onChange={(event) => setForm((value) => ({ ...value, ipDownloadLimit: Number(event.target.value) }))} />
        </label>
        <label>
          错误口令上限
          <input type="number" min="1" max="100" value={form.wrongPassphraseLimit} onChange={(event) => setForm((value) => ({ ...value, wrongPassphraseLimit: Number(event.target.value) }))} />
        </label>
        <label className="check-row">
          <input type="checkbox" checked={form.realOnly} onChange={(event) => setForm((value) => ({ ...value, realOnly: event.target.checked }))} />
          只选择 Xray 真实检测通过节点
        </label>
        <label className="check-row">
          <input type="checkbox" checked={form.requiresPassphrase} onChange={(event) => setForm((value) => ({ ...value, requiresPassphrase: event.target.checked }))} />
          需要口令
        </label>
        <label className="check-row">
          <input type="checkbox" checked={form.allowPublicClaim} onChange={(event) => setForm((value) => ({ ...value, allowPublicClaim: event.target.checked }))} />
          允许公开领取页
        </label>
        <label className="check-row">
          <input type="checkbox" checked={form.allowAutomation} onChange={(event) => setForm((value) => ({ ...value, allowAutomation: event.target.checked }))} />
          允许 Hermes / OpenClaw 自动化读取
        </label>
        <label className="check-row">
          <input type="checkbox" checked={form.allowHermesLink} onChange={(event) => setForm((value) => ({ ...value, allowHermesLink: event.target.checked }))} />
          允许自动化读取领取链接
        </label>
        <label className="check-row">
          <input type="checkbox" checked={form.allowHermesFile} onChange={(event) => setForm((value) => ({ ...value, allowHermesFile: event.target.checked }))} />
          允许自动化下载文件
        </label>
        <label className="check-row">
          <input type="checkbox" checked={false} readOnly />
          生成后保持草稿
        </label>
        <button className="primary small" disabled={exporting}>
          <FileArchive size={16} />
          {exporting ? "生成中..." : "生成节点包"}
        </button>
      </form>
      <h3>当前发布批次</h3>
      <BatchTable batches={currentBatch ? [currentBatch] : []} videoMode={videoMode} onPublish={onPublish} onClose={onClose} onDeleteDraft={onDeleteDraft} onPreflight={onPreflight} />
      <h3>草稿批次</h3>
      <BatchTable batches={drafts} videoMode={videoMode} onPublish={onPublish} onClose={onClose} onDeleteDraft={onDeleteDraft} onPreflight={onPreflight} />
      <h3>历史批次</h3>
      <BatchTable batches={batches.filter((batch) => batch.status !== "draft" && batch.status !== "published")} videoMode={videoMode} onPublish={onPublish} onClose={onClose} onDeleteDraft={onDeleteDraft} onPreflight={onPreflight} />
    </section>
  );
}

function ClaimPanel({
  batches,
  videoMode,
  onPublish,
  onClose,
  onDeleteDraft,
  onPreflight
}: {
  batches: ExportBatch[];
  videoMode: boolean;
  onPublish: (batch: ExportBatch) => void;
  onClose: (batch: ExportBatch) => void;
  onDeleteDraft: (batch: ExportBatch) => void;
  onPreflight: (batch: ExportBatch) => void;
}) {
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>领取页管理</h2>
          <p className="muted compact">公开领取页只显示口令输入和领取按钮，不展示后台包列表。只有已发布批次可以领取。</p>
        </div>
      </div>
      <BatchTable batches={batches} claimOnly videoMode={videoMode} onPublish={onPublish} onClose={onClose} onDeleteDraft={onDeleteDraft} onPreflight={onPreflight} />
    </section>
  );
}

function SubscriptionPanel({
  form,
  setForm,
  activities,
  videoMode,
  onSubmit,
  onRebuild,
  onHealthCheck,
  onRefreshCache
}: {
  form: SubscriptionFormState;
  setForm: React.Dispatch<React.SetStateAction<SubscriptionFormState>>;
  activities: SubscriptionActivity[];
  videoMode: boolean;
  onSubmit: (event: React.FormEvent) => void;
  onRebuild: (activity: SubscriptionActivity) => void;
  onHealthCheck: (activity: SubscriptionActivity) => void;
  onRefreshCache: (activity: SubscriptionActivity) => void;
}) {
  const current = activities.find((item) => item.status === "published");
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>自动节点订阅池</h2>
          <p className="muted compact">每期 YouTube 视频对应一个订阅活动。粉丝输入本期口令后复制 raw / base64 订阅链接，ZIP 仅保留为后台备用导出。</p>
        </div>
        <Link2 size={18} />
      </div>
      <div className="notice">订阅访问只读取缓存内容，不会触发实时采集或 Xray 检测。健康检查用于替换失效或明显劣化节点，不会每 5 分钟全量洗牌。</div>

      <form className="subscription-form" onSubmit={onSubmit}>
        <label>
          活动名称
          <input value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} />
        </label>
        <label>
          视频备注
          <input value={form.videoNote} placeholder="例如：2026年6月第1期公开视频" onChange={(event) => setForm((value) => ({ ...value, videoNote: event.target.value }))} />
        </label>
        <label>
          本期视频口令
          <input type="password" value={form.passphrase} onChange={(event) => setForm((value) => ({ ...value, passphrase: event.target.value }))} />
        </label>
        <label>
          开始时间
          <input type="datetime-local" value={form.startsAt} onChange={(event) => setForm((value) => ({ ...value, startsAt: event.target.value }))} />
        </label>
        <label>
          截止时间
          <input type="datetime-local" value={form.expiresAt} onChange={(event) => setForm((value) => ({ ...value, expiresAt: event.target.value }))} />
        </label>
        <label>
          输出节点数
          <input type="number" min="1" max="200" value={form.outputCount} onChange={(event) => setForm((value) => ({ ...value, outputCount: Number(event.target.value) }))} />
        </label>
        <label>
          目标延迟 ms
          <input type="number" min="1" value={form.targetLatencyMs} onChange={(event) => setForm((value) => ({ ...value, targetLatencyMs: Number(event.target.value) }))} />
        </label>
        <label>
          警告延迟 ms
          <input type="number" min="1" value={form.warningLatencyMs} onChange={(event) => setForm((value) => ({ ...value, warningLatencyMs: Number(event.target.value) }))} />
        </label>
        <label>
          淘汰延迟 ms
          <input type="number" min="1" value={form.removeLatencyMs} onChange={(event) => setForm((value) => ({ ...value, removeLatencyMs: Number(event.target.value) }))} />
        </label>
        <label>
          健康检查间隔分钟
          <input type="number" min="1" value={form.healthCheckIntervalMinutes} onChange={(event) => setForm((value) => ({ ...value, healthCheckIntervalMinutes: Number(event.target.value) }))} />
        </label>
        <button className="primary small" type="submit"><Link2 size={16} /> 创建订阅活动</button>
      </form>

      <h3>当前订阅活动</h3>
      <SubscriptionTable activities={current ? [current] : []} videoMode={videoMode} onRebuild={onRebuild} onHealthCheck={onHealthCheck} onRefreshCache={onRefreshCache} />
      <h3>历史订阅活动</h3>
      <SubscriptionTable activities={activities.filter((item) => item.id !== current?.id)} videoMode={videoMode} onRebuild={onRebuild} onHealthCheck={onHealthCheck} onRefreshCache={onRefreshCache} />
    </section>
  );
}

function SubscriptionTable({
  activities,
  videoMode,
  onRebuild,
  onHealthCheck,
  onRefreshCache
}: {
  activities: SubscriptionActivity[];
  videoMode: boolean;
  onRebuild: (activity: SubscriptionActivity) => void;
  onHealthCheck: (activity: SubscriptionActivity) => void;
  onRefreshCache: (activity: SubscriptionActivity) => void;
}) {
  return (
    <div className="table spaced">
      <div className="table-head subscription-grid"><span>活动</span><span>状态</span><span>截止时间</span><span>输出</span><span>领取页</span><span>订阅链接</span><span>统计</span><span>操作</span></div>
      {activities.map((activity) => {
        const claimUrl = `/r/${activity.claim_slug}`;
        const rawUrl = `/sub/${activity.subscription_token}/raw`;
        const base64Url = `/sub/${activity.subscription_token}/base64`;
        return (
          <div className="table-row subscription-grid" key={activity.id}>
            <span className="truncate">{activity.name}</span>
            <span>{zhStatus(activity.status)}</span>
            <span>{formatDate(activity.expires_at)}</span>
            <span>{activity.output_count} 条{activity.risk_status === "insufficient" ? " / 不足" : ""}</span>
            <span className="truncate">{videoMode ? `/r/${maskSlug(activity.claim_slug)}` : claimUrl}</span>
            <span className="truncate">{videoMode ? `/sub/${maskSlug(activity.subscription_token)}/raw` : rawUrl}<br />{videoMode ? `/sub/${maskSlug(activity.subscription_token)}/base64` : base64Url}</span>
            <span>访问 {activity.view_count ?? 0}<br />订阅 {Number(activity.raw_access_count ?? 0) + Number(activity.base64_access_count ?? 0)}<br />替换 {activity.last_replacement_count ?? 0}<br />IP {activity.active_ip_count ?? 0}</span>
            <span className="row-actions">
              <button className="link-button" type="button" onClick={() => onHealthCheck(activity)}>健康检查</button>
              <button className="link-button" type="button" onClick={() => onRebuild(activity)}>重建池</button>
              <button className="link-button" type="button" onClick={() => onRefreshCache(activity)}>刷新缓存</button>
            </span>
          </div>
        );
      })}
      {!activities.length && <p className="muted">暂无订阅活动。创建活动后，粉丝可以通过公开领取页输入视频口令获取订阅链接。</p>}
    </div>
  );
}

function StatsPanel({ stats, channelStats }: { stats: BatchStat[]; channelStats: ChannelStat[] }) {
  return (
    <>
      <section className="panel">
        <div className="panel-title"><h2>领取统计</h2><BarChart3 size={18} /></div>
        <div className="table">
          <div className="table-head stats-grid"><span>批次</span><span>访问</span><span>口令输入</span><span>正确</span><span>错误</span><span>下载</span><span>反馈</span></div>
          {stats.map((item) => (
            <div className="table-row stats-grid" key={item.id}>
              <span>{item.batch_code}</span>
              <span>{item.view_count ?? 0}</span>
              <span>{item.passphrase_attempt_count ?? 0}</span>
              <span>{item.passphrase_correct_count ?? 0}</span>
              <span>{item.passphrase_wrong_count ?? 0}</span>
              <span>{item.download_count ?? 0}</span>
              <span>{item.feedback_count ?? 0}</span>
            </div>
          ))}
          {!stats.length && <p className="muted">暂无统计数据。</p>}
        </div>
      </section>
      <section className="panel">
        <div className="panel-title"><h2>渠道来源统计</h2><BarChart3 size={18} /></div>
        <div className="table">
          <div className="table-head stats-grid"><span>渠道</span><span>访问</span><span>口令输入</span><span>下载</span><span>反馈</span><span>问题率</span><span>转化率</span></div>
          {channelStats.map((item) => {
            const views = item.view_count ?? 0;
            const downloads = item.download_count ?? 0;
            const feedbacks = item.feedback_count ?? 0;
            const unusable = item.unusable_feedback_count ?? 0;
            return (
              <div className="table-row stats-grid" key={item.source_platform}>
                <span>{channelName(item.source_platform)}</span>
                <span>{views}</span>
                <span>{item.passphrase_attempt_count ?? 0}</span>
                <span>{downloads}</span>
                <span>{feedbacks}</span>
                <span>{feedbacks ? `${Math.round((unusable / feedbacks) * 100)}%` : "-"}</span>
                <span>{views ? `${Math.round((downloads / views) * 100)}%` : "-"}</span>
              </div>
            );
          })}
          {!channelStats.length && <p className="muted">暂无渠道统计。</p>}
        </div>
      </section>
    </>
  );
}

function FeedbackPanel({
  feedback,
  onStatusChange
}: {
  feedback: FeedbackItem[];
  onStatusChange: (item: FeedbackItem, processStatus: string) => void;
}) {
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>节点使用反馈分析</h2>
          <p className="muted compact">用于判断哪些渠道、设备、客户端或网络环境更容易出现问题。</p>
        </div>
        <MessageSquare size={18} />
      </div>
      <div className="table">
        <div className="table-head feedback-grid"><span>时间</span><span>渠道</span><span>批次</span><span>设备</span><span>软件</span><span>问题类型</span><span>处理状态</span><span>备注</span><span>操作</span></div>
        {feedback.map((item) => (
          <div className="table-row feedback-grid" key={item.id}>
            <span>{formatDate(item.created_at)}</span>
            <span>{channelName(item.source_platform)}</span>
            <span>{item.batch_code ?? "-"}</span>
            <span>{item.device || "-"}</span>
            <span>{item.client_app || "-"}</span>
            <span>{item.is_usable === 1 ? "能用" : item.is_usable === 0 ? zhIssue(item.issue_type) : zhIssue(item.issue_type)}</span>
            <span>{zhProcess(item.process_status)}</span>
            <span className="truncate">{item.note || "-"}</span>
            <span className="row-actions">
              <button className="link-button" type="button" onClick={() => onStatusChange(item, "viewed")}>已查看</button>
              <button className="link-button" type="button" onClick={() => onStatusChange(item, "resolved")}>已解决</button>
              <button className="link-button" type="button" onClick={() => onStatusChange(item, "regenerate")}>需重做包</button>
            </span>
          </div>
        ))}
        {!feedback.length && <p className="muted">暂无反馈。粉丝在公开领取页下载后提交“能用 / 不能用”反馈，这里会显示分析记录。</p>}
      </div>
    </section>
  );
}

function AutomationPanel({ batches, videoMode }: { batches: ExportBatch[]; videoMode: boolean }) {
  const allowed = batches.filter((batch) => batch.status === "published" && batch.allow_automation);
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <h2>自动化接口</h2>
          <p className="muted compact">给 Hermes / OpenClaw / 定时任务读取，只读，不负责自动发布平台内容。</p>
        </div>
        <Link2 size={18} />
      </div>
      {videoMode && <div className="notice">当前已开启录屏模式，API Token、完整接口地址、完整 slug 和服务器地址已隐藏。</div>}
      <div className="settings-list">
        <div className="setting-card">
          <strong>只读接口</strong>
          <p className="muted compact">/api/automation/packages、/current-package、/channel-links、/daily-summary、/stats-summary</p>
        </div>
        <div className="setting-card">
          <strong>Token 状态</strong>
          <p className="muted compact">{videoMode ? "已隐藏" : "通过 AUTOMATION_API_TOKEN 环境变量启用"}</p>
        </div>
        <div className="setting-card">
          <strong>高质量包保护</strong>
          <p className="muted compact">0-100ms 高质量包默认不允许自动化读取，除非手动开启自动化和 Hermes 权限。</p>
        </div>
        <div className="setting-card">
          <strong>daily-summary</strong>
          <p className="muted compact">返回固定模板摘要，不调用 AI，不消耗大模型 Token。</p>
        </div>
      </div>
      <h3>允许自动化读取的节点包</h3>
      <div className="table spaced">
        <div className="table-head batch-grid"><span>批次</span><span>名称</span><span>状态</span><span>档位</span><span>数量</span><span>权限</span><span>接口</span></div>
        {allowed.map((batch) => (
          <div className="table-row batch-grid" key={batch.id}>
            <span>{formatDate(batch.created_at)}</span>
            <span className="truncate">{batch.name}</span>
            <span>{zhStatus(batch.status)}</span>
            <span>{zhQuality(batch.quality_tier)}</span>
            <span>{batch.node_count}</span>
            <span>{batch.allow_hermes_file ? "文件+链接" : batch.allow_hermes_link ? "仅链接" : "仅摘要"}</span>
            <span className="truncate">{videoMode ? "/api/automation/****" : `/api/automation/packages/${batch.id}`}</span>
          </div>
        ))}
        {!allowed.length && <p className="muted">暂无允许自动化读取的已发布节点包。草稿、关闭、过期、已替换或未授权自动化的包不会出现在这里。</p>}
      </div>
    </section>
  );
}

function SettingsPanel({ videoMode, onToggleVideoMode, summary }: { videoMode: boolean; onToggleVideoMode: () => void; summary: Summary | null }) {
  const settingGroups = [
    ["基础设置", "后台访问地址、公开领取基础地址、系统名称、系统版本、运行状态。"],
    ["管理员设置", "管理员账号、修改密码入口、退出登录、登录会话有效期。"],
    ["安全设置", "登录失败限制、Session 过期、公开领取限速、口令错误限制、单 IP 下载限制、录屏模式。"],
    ["采集设置", "默认采集来源、采集超时时间、采集并发、自动去重。"],
    ["测试设置", "基础测试开关、Xray-core 真实检测开关、内核路径、低并发、单节点超时、本地端口范围、异常进程清理。"],
    ["节点包档位", "高质量包 0-100ms、普通优质包 100-200ms、社群福利包 200-300ms、备用包 300ms 以上，阈值后续可配置。"],
    ["节点包设置", "默认导出数量、默认最大延迟、是否需要口令、公开领取、自动化读取、下载次数限制。"],
    ["自动化接口", "API Token 管理、只读接口、daily-summary 固定模板、Hermes 读取边界和调用日志。"],
    ["领取页设置", "公开领取域名、默认说明文案、反馈入口、noindex、渠道统计。"],
    ["备份与恢复", "数据目录、节点包目录、备份目录、一键备份和恢复规划。"]
  ];
  return (
    <section className="panel">
      <div className="panel-title"><h2>系统设置</h2><Settings size={18} /></div>
      {videoMode && <div className="notice">当前已开启录屏模式，敏感信息已隐藏。</div>}
      <div className="settings-grid">
        <div>
          <strong>公开视频模式</strong>
          <p className="muted compact">开启后隐藏管理员账号、完整节点、来源链接、Token、IP、UUID、密码等敏感信息。</p>
        </div>
        <button className={videoMode ? "primary small" : "icon"} onClick={onToggleVideoMode} type="button">
          {videoMode ? "已开启" : "开启"}
        </button>
        <div>
          <strong>系统状态</strong>
          <p className="muted compact">{zhStatus(summary?.systemStatus ?? "running")} / v{summary?.version ?? "1.1.0"}</p>
        </div>
      </div>
      <div className="settings-list">
        {settingGroups.map(([title, text]) => (
          <div className="setting-card" key={title}>
            <strong>{title}</strong>
            <p className="muted compact">{text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function LogsPanel({ logs }: { logs: LogItem[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>运行日志</h2><ScrollText size={18} /></div>
      <div className="table">
        <div className="table-head log-grid"><span>时间</span><span>级别</span><span>摘要</span></div>
        {logs.map((log, index) => (
          <div className="table-row log-grid" key={`${log.created_at}-${index}`}>
            <span>{formatDate(log.created_at)}</span>
            <span>{logLevelName(log.level)}</span>
            <span className="truncate">{log.message}</span>
          </div>
        ))}
        {!logs.length && <p className="muted">暂无运行日志。系统产生采集、测试、导出、领取、反馈或错误事件后，会在这里显示记录。</p>}
      </div>
    </section>
  );
}

function PublicClaimPage({ slug }: { slug: string }) {
  const [batch, setBatch] = React.useState<PublicBatch | null>(null);
  const [found, setFound] = React.useState(true);
  const [unlocked, setUnlocked] = React.useState(false);
  const [passphrase, setPassphrase] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [feedback, setFeedback] = React.useState({
    device: "",
    clientApp: "",
    issueType: "other",
    isUsable: true,
    note: ""
  });

  React.useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex,nofollow";
    document.head.appendChild(meta);
    apiFetch(`/api/public/claim/${slug}${window.location.search}`)
      .then((res) => res.json())
      .then((data) => {
        setFound(data.found);
        setBatch(data.batch ?? null);
        setUnlocked(Boolean(data.unlocked));
      })
      .catch(() => setFound(false));
    return () => {
      document.head.removeChild(meta);
    };
  }, [slug]);

  async function verify(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    const res = await apiFetch(`/api/public/claim/${slug}/verify${window.location.search}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase })
    });
    const data = await res.json();
    if (!res.ok) {
      setMessage(data.message ?? "口令验证失败");
      return;
    }
    setUnlocked(true);
    setMessage("口令正确，可以下载备用节点文件。");
  }

  async function submitFeedback(event: React.FormEvent) {
    event.preventDefault();
    const res = await apiFetch(`/api/public/claim/${slug}/feedback${window.location.search}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(feedback)
    });
    setMessage(res.ok ? "反馈已提交，谢谢。" : "反馈提交失败。");
  }

  if (!found) {
    return <main className="public-shell"><section className="public-panel"><h1>领取页不可用</h1><p>批次不存在、未发布或已过期。</p></section></main>;
  }

  return (
    <main className="public-shell">
      <section className="public-panel">
        <h1>{batch?.title ?? "节点包领取"}</h1>
        <p>{batch?.description || "输入正确口令后即可领取节点内容。公开页不会展示后台来源、测试细节或完整节点池。"}</p>
        <div className="public-meta">
          <span>有效期：{batch?.expiresAt ? new Date(batch.expiresAt).toLocaleString() : "未设置"}</span>
        </div>

        <form className="login-form" onSubmit={verify}>
          <label>
            领取口令
            <input type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} />
          </label>
          <button className="primary">验证口令</button>
        </form>

        {unlocked && (
          <>
            <a className="download-button" href={`/api/public/claim/${slug}/download${window.location.search}`}>
              <Download size={18} />
              下载备用节点文件
            </a>
            <div className="feedback-card">
              <h2>节点包能正常使用吗？</h2>
              <div className="choice-row">
                <button type="button" className={feedback.isUsable ? "primary small" : "icon"} onClick={() => setFeedback((value) => ({ ...value, isUsable: true }))}>能用</button>
                <button type="button" className={!feedback.isUsable ? "primary small" : "icon"} onClick={() => setFeedback((value) => ({ ...value, isUsable: false }))}>不能用</button>
                <button type="button" className={feedback.issueType === "partial_available" ? "primary small" : "icon"} onClick={() => setFeedback((value) => ({ ...value, isUsable: false, issueType: "partial_available" }))}>部分可用</button>
              </div>
            </div>
          </>
        )}

        {message && <div className="notice">{message}</div>}

        <form className="feedback-form" onSubmit={submitFeedback}>
          <h2>遇到问题？点这里反馈</h2>
          <select value={feedback.device} onChange={(event) => setFeedback((value) => ({ ...value, device: event.target.value }))}>
            <option value="">选择设备系统</option>
            <option value="Windows">Windows</option>
            <option value="iPhone">iPhone</option>
            <option value="Android">Android</option>
            <option value="Mac">Mac</option>
            <option value="其他">其他</option>
          </select>
          <select value={feedback.clientApp} onChange={(event) => setFeedback((value) => ({ ...value, clientApp: event.target.value }))}>
            <option value="">选择客户端软件</option>
            <option value="v2rayN">v2rayN</option>
            <option value="Clash Verge">Clash Verge</option>
            <option value="Shadowrocket">Shadowrocket</option>
            <option value="sing-box">sing-box</option>
            <option value="其他">其他</option>
          </select>
          <select value={feedback.issueType} onChange={(event) => setFeedback((value) => ({ ...value, issueType: event.target.value }))}>
            {Object.entries(issueText).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <textarea maxLength={200} placeholder="备注，可选，最多 200 字" value={feedback.note} onChange={(event) => setFeedback((value) => ({ ...value, note: event.target.value }))} />
          <button className="primary small">提交反馈</button>
        </form>
      </section>
    </main>
  );
}

function PublicSubscriptionClaimPage({ slug }: { slug: string }) {
  const [batch, setBatch] = React.useState<PublicBatch | null>(null);
  const [found, setFound] = React.useState(true);
  const [unlocked, setUnlocked] = React.useState(false);
  const [passphrase, setPassphrase] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [copyMessage, setCopyMessage] = React.useState("");
  const [feedback, setFeedback] = React.useState({
    device: "",
    clientApp: "",
    issueType: "other",
    isUsable: true,
    note: ""
  });

  React.useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex,nofollow";
    document.head.appendChild(meta);
    apiFetch(`/api/public/claim/${slug}${window.location.search}`)
      .then((res) => res.json())
      .then((data) => {
        setFound(data.found);
        setBatch(data.batch ?? null);
        setUnlocked(Boolean(data.unlocked));
      })
      .catch(() => setFound(false));
    return () => {
      document.head.removeChild(meta);
    };
  }, [slug]);

  async function verify(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    const res = await apiFetch(`/api/public/claim/${slug}/verify${window.location.search}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase })
    });
    const data = await res.json();
    if (!res.ok) {
      setMessage(data.message ?? "口令验证失败");
      return;
    }
    setUnlocked(true);
    setBatch((value) => value ? ({ ...value, rawUrl: data.rawUrl ?? value.rawUrl, base64Url: data.base64Url ?? value.base64Url }) : value);
    setMessage(data.mode === "subscription" ? "口令正确，请复制 raw 或 base64 订阅链接导入客户端。" : "口令正确，可以下载备用节点文件。");
  }

  async function copyLink(value?: string | null) {
    if (!value) {
      setCopyMessage("暂无可复制链接");
      return;
    }
    const ok = await copyText(value);
    setCopyMessage(ok ? "链接已复制" : "复制失败，请手动复制输入框里的链接");
  }

  async function submitFeedback(event: React.FormEvent) {
    event.preventDefault();
    const res = await apiFetch(`/api/public/claim/${slug}/feedback${window.location.search}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(feedback)
    });
    setMessage(res.ok ? "反馈已提交，谢谢。" : "反馈提交失败。");
  }

  if (!found) {
    return <main className="public-shell"><section className="public-panel"><h1>领取页不可用</h1><p>本期订阅不存在、未发布或已关闭。</p></section></main>;
  }

  const isSubscription = batch?.mode === "subscription" || Boolean(batch?.rawUrl || batch?.base64Url);

  return (
    <main className="public-shell">
      <section className="public-panel">
        <h1>{batch?.title ?? "免费节点订阅领取"}</h1>
        <p>{batch?.description || "输入本期视频口令后，即可复制通用订阅链接。免费节点存在时效性，请以实际使用为准。"}</p>
        <div className="public-meta">
          <span>截止时间：{batch?.expiresAt ? new Date(batch.expiresAt).toLocaleString() : "未设置"}</span>
          <span>剩余时间：{formatRemaining(batch?.remainingSeconds)}</span>
          {batch?.outputCount ? <span>订阅输出：{batch.outputCount} 条以内</span> : null}
        </div>
        {batch?.riskMessage && <div className="notice">{batch.riskMessage}</div>}

        {!unlocked && (
          <form className="login-form" onSubmit={verify}>
            <label>
              本期订阅解锁码
              <input type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} />
            </label>
            <button className="primary">验证并领取订阅</button>
          </form>
        )}

        {unlocked && isSubscription && (
          <div className="subscription-links">
            <h2>复制订阅链接</h2>
            <p className="muted compact">默认提供通用 raw 和 base64 订阅。需要 Clash / sing-box 专用格式的用户，可使用订阅转换工具自行转换。</p>
            <CopyField label="raw 通用订阅" value={batch?.rawUrl ?? ""} onCopy={() => copyLink(batch?.rawUrl)} />
            <CopyField label="base64 通用订阅" value={batch?.base64Url ?? ""} onCopy={() => copyLink(batch?.base64Url)} />
            <p className="muted compact">免费节点存在时效性，系统会在有效期内维护并替换失效或明显劣化节点，实际体验受你的网络环境影响。</p>
          </div>
        )}

        {unlocked && !isSubscription && (
          <a className="download-button" href={`/api/public/claim/${slug}/download${window.location.search}`}>
            <Download size={18} />
            下载备用节点文件
          </a>
        )}

        {copyMessage && <div className="notice">{copyMessage}</div>}
        {message && <div className="notice">{message}</div>}

        {unlocked && (
          <div className="feedback-card">
            <h2>这个订阅能正常使用吗？</h2>
            <div className="choice-row">
              <button type="button" className={feedback.isUsable ? "primary small" : "icon"} onClick={() => setFeedback((value) => ({ ...value, isUsable: true }))}>能用</button>
              <button type="button" className={!feedback.isUsable && feedback.issueType !== "partial_available" ? "primary small" : "icon"} onClick={() => setFeedback((value) => ({ ...value, isUsable: false, issueType: "other" }))}>不能用</button>
              <button type="button" className={feedback.issueType === "partial_available" ? "primary small" : "icon"} onClick={() => setFeedback((value) => ({ ...value, isUsable: false, issueType: "partial_available" }))}>部分可用</button>
            </div>
          </div>
        )}

        <form className="feedback-form" onSubmit={submitFeedback}>
          <h2>遇到问题？点这里反馈</h2>
          <select value={feedback.device} onChange={(event) => setFeedback((value) => ({ ...value, device: event.target.value }))}>
            <option value="">选择设备系统</option>
            <option value="Windows">Windows</option>
            <option value="iPhone">iPhone</option>
            <option value="Android">Android</option>
            <option value="Mac">Mac</option>
            <option value="其他">其他</option>
          </select>
          <select value={feedback.clientApp} onChange={(event) => setFeedback((value) => ({ ...value, clientApp: event.target.value }))}>
            <option value="">选择客户端软件</option>
            <option value="v2rayN">v2rayN</option>
            <option value="Clash Verge">Clash Verge</option>
            <option value="Shadowrocket">Shadowrocket</option>
            <option value="sing-box">sing-box</option>
            <option value="其他">其他</option>
          </select>
          <select value={feedback.issueType} onChange={(event) => setFeedback((value) => ({ ...value, issueType: event.target.value }))}>
            {Object.entries(issueText).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <textarea maxLength={200} placeholder="备注，可选，最多 200 字" value={feedback.note} onChange={(event) => setFeedback((value) => ({ ...value, note: event.target.value }))} />
          <button className="primary small">提交反馈</button>
        </form>
      </section>
    </main>
  );
}

function CopyField({ label, value, onCopy }: { label: string; value: string; onCopy: () => void }) {
  return (
    <label className="copy-field">
      {label}
      <div>
        <input readOnly value={value} onFocus={(event) => event.currentTarget.select()} />
        <button type="button" className="primary small" onClick={onCopy}>复制链接</button>
      </div>
    </label>
  );
}

function RunTable({ runs }: { runs: CollectionRun[] }) {
  return (
    <div className="table">
      <div className="table-head run-grid"><span>任务</span><span>状态</span><span>来源</span><span>原始</span><span>新增</span><span>错误</span></div>
      {runs.slice(0, 12).map((run) => (
        <div className="table-row run-grid" key={run.id}>
          <span>第 {run.id} 批</span><span>{zhStatus(run.status)}</span><span>{run.fetched_sources}/{run.discovered_sources}</span><span>{run.raw_nodes}</span><span>{run.inserted_nodes}</span><span>{run.error_count}</span>
        </div>
      ))}
      {!runs.length && <p className="muted">暂无采集任务记录。</p>}
    </div>
  );
}

function TestRunTable({ runs }: { runs: TestRun[] }) {
  return (
    <div className="table">
      <div className="table-head run-grid"><span>任务</span><span>状态</span><span>测试</span><span>通过</span><span>失败</span><span>均值</span></div>
      {runs.slice(0, 12).map((run) => (
        <div className="table-row run-grid" key={run.id}>
          <span>第 {run.id} 批</span><span>{zhStatus(run.status)}</span><span>{run.tested_nodes}</span><span>{run.passed_nodes}</span><span>{run.failed_nodes}</span><span>{run.avg_latency_ms ? `${run.avg_latency_ms}ms` : "-"}</span>
        </div>
      ))}
      {!runs.length && <p className="muted">暂无测试任务记录。</p>}
    </div>
  );
}

function BatchTable({
  batches,
  compact = false,
  claimOnly = false,
  videoMode,
  onPublish,
  onClose,
  onDeleteDraft,
  onPreflight
}: {
  batches: ExportBatch[];
  compact?: boolean;
  claimOnly?: boolean;
  videoMode: boolean;
  onPublish: (batch: ExportBatch) => void;
  onClose: (batch: ExportBatch) => void;
  onDeleteDraft: (batch: ExportBatch) => void;
  onPreflight: (batch: ExportBatch) => void;
}) {
  return (
    <div className="table spaced">
      <div className="table-head batch-grid"><span>批次</span><span>名称</span><span>状态</span><span>档位</span><span>数量</span><span>权限</span><span>领取页 / 操作</span></div>
      {batches.slice(0, compact ? 6 : 50).map((batch) => {
        const claimUrl = `/r/${batch.public_slug}`;
        const displayUrl = videoMode ? `/r/${maskSlug(batch.public_slug)}` : claimUrl;
        return (
          <div className="table-row batch-grid" key={batch.id}>
            <span>{formatDate(batch.created_at)}</span>
            <span className="truncate">{batch.name}</span>
            <span>{zhStatus(batch.status)}</span>
            <span>{zhQuality(batch.quality_tier)}</span>
            <span>{batch.node_count}</span>
            <span>{batch.allow_automation ? "自动化可读" : "后台手动"}</span>
            <span className="row-actions">
              <button className="link-button" type="button" onClick={() => onPreflight(batch)}>发布前检查</button>
              {batch.status === "published" ? (
                <>
                  <a className="text-link" href={claimUrl} target="_blank" rel="noreferrer">{claimOnly ? "预览" : displayUrl}</a>
                  <button className="link-button" type="button" onClick={() => navigator.clipboard?.writeText(`${window.location.origin}${claimUrl}`)}>复制链接</button>
                  <button className="link-button danger-text" type="button" onClick={() => onClose(batch)}>关闭</button>
                </>
              ) : batch.status === "draft" ? (
                <>
                  <button className="link-button" type="button" onClick={() => onPublish(batch)}>发布此批次</button>
                  <button className="link-button danger-text" type="button" onClick={() => onDeleteDraft(batch)}><Trash2 size={14} /> 删除草稿</button>
                </>
              ) : (
                <span className="muted">{zhStatus(batch.status)}</span>
              )}
            </span>
          </div>
        );
      })}
      {!batches.length && <p className="muted">暂无导出批次。</p>}
    </div>
  );
}

function NodePreview({ title, nodes }: { title: string; nodes: NodeItem[] }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>{title}</h2><Activity size={18} /></div>
      <NodeTable nodes={nodes} />
    </section>
  );
}

function NodeTable({ nodes }: { nodes: NodeItem[] }) {
  return (
    <div className="table">
      <div className="table-head node-grid"><span>协议</span><span>状态</span><span>基础延迟</span><span>真实延迟</span><span>档位</span><span>测试方式</span><span>最近测试</span><span>失败原因</span></div>
      {nodes.map((node) => (
        <div className="table-row node-grid" key={node.id}>
          <span>{node.protocol}</span>
          <span>{zhStatus(node.status)}</span>
          <span>{node.latency_ms ? `${node.latency_ms}ms` : "-"}</span>
          <span>{node.real_latency_ms ? `${node.real_latency_ms}ms` : "-"}</span>
          <span>{zhQuality(node.quality_tier)}</span>
          <span>{node.test_method === "xray-core" ? "Xray-core 真实检测" : "TCP 基础测试"}</span>
          <span>{formatDate(node.real_tested_at ?? node.last_tested_at)}</span>
          <span className="truncate">{zhFailure(node.failure_reason)}</span>
        </div>
      ))}
      {!nodes.length && <p className="muted">暂无节点记录。</p>}
    </div>
  );
}

function SourceCache({ sources, videoMode }: { sources: SourceItem[]; videoMode: boolean }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>来源缓存</h2><GitBranch size={18} /></div>
      <div className="table">
        <div className="table-head source-grid"><span>类型</span><span>状态</span><span>成功</span><span>失败</span><span>来源 URL</span></div>
        {sources.slice(0, 20).map((source) => (
          <div className="table-row source-grid" key={source.id}>
            <span>{source.source_type}</span><span>{zhStatus(source.status)}</span><span>{source.success_count}</span><span>{source.failure_count}</span><span className="truncate">{videoMode ? maskUrl(source.url) : source.url}</span>
          </div>
        ))}
        {!sources.length && <p className="muted">暂无来源缓存。</p>}
      </div>
    </section>
  );
}

function LatencyDistribution({ summary }: { summary: Summary | null }) {
  return (
    <section className="panel">
      <div className="panel-title"><h2>后台初筛延迟分布</h2><Database size={18} /></div>
      <div className="distribution">
        {(summary?.latencyDistribution ?? []).map((item) => (
          <div key={item.label} className="bar-row">
            <span>{item.label}</span>
            <div className="bar"><i style={{ width: `${Math.min(item.count * 5, 100)}%` }} /></div>
            <strong>{item.count}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function maskUrl(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}/...`;
  } catch {
    return "已隐藏";
  }
}

function maskSlug(slug: string) {
  if (slug.length <= 6) return "***";
  return `${slug.slice(0, 3)}***${slug.slice(-3)}`;
}

async function copyText(value: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // HTTP pages may block navigator.clipboard, fall back below.
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "true");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}

function formatRemaining(seconds?: number) {
  if (seconds === undefined || seconds === null) return "-";
  if (seconds <= 0) return "已到期";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  if (days > 0) return `${days} 天 ${hours} 小时`;
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} 小时 ${minutes} 分钟`;
}

function formatTime(value?: string | null) {
  return formatDate(value);
}

function channelName(value?: string | null) {
  const key = (value || "direct").toLowerCase();
  const names: Record<string, string> = {
    youtube: "YouTube",
    youtube_desc: "YouTube 简介",
    youtube_pin: "YouTube 置顶评论",
    telegram: "Telegram",
    facebook: "Facebook",
    x: "X / Twitter",
    twitter: "X / Twitter",
    tiktok: "TikTok",
    direct: "直接访问"
  };
  return names[key] ?? "其他";
}

function logLevelName(value?: string | null) {
  const names: Record<string, string> = {
    info: "信息",
    warning: "警告",
    warn: "警告",
    error: "错误",
    success: "成功",
    debug: "调试"
  };
  return value ? names[value] ?? value : "-";
}

function riskText(value?: string | null) {
  const names: Record<string, string> = {
    low: "较低",
    medium: "中等",
    high: "较高"
  };
  return value ? names[value] ?? value : "-";
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return "-";
  return time.toLocaleString();
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
